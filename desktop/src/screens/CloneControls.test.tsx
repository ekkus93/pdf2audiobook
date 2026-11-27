import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
vi.mock("../engine/api", () => ({ run: vi.fn(async () => ({ outcome: "success", result: { models: [{ name: "kitten2", ready: false, package_installed: true, weights_present: false, download_bytes: 1600000000, directory: "/model-cache", transcription_ready: false }] } })), errorMessage: () => "Picker unavailable" }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn(async () => "/clips/speaker.wav") }));
import { CloneControls } from "./CloneControls";
import { cloneRequest, defaults, isCloning, requests, validate, type CloneForm } from "./bookOptions";
import { CONFIG } from "./bookOptions.test";

function Harness() {
  const [form, setForm] = useState<CloneForm>({ voiceMode: "clone", referenceText: "Old words", referenceTextFile: "" });
  return <CloneControls form={form} onChange={setForm} />;
}
describe("voice cloning options", () => {
  it("keeps configured private references implicit and never passes redaction placeholders", () => {
    const form = defaults({ ...CONFIG, tts: { ...CONFIG.tts, voice_clone: { enabled: true, reference_audio: "***", reference_text_file: "***" } } }, 2);
    expect(isCloning(form)).toBe(true);
    expect(validate(form, 2)).toEqual({});
    const request = requests("book.pdf", form, null).convert;
    expect(request.command === "convert" && request.convert.voice).toBeNull();
    expect(JSON.stringify(request)).not.toContain("***");
    expect(cloneRequest(form)).toEqual({});
    expect(cloneRequest({ ...form, voiceMode: "builtin", referenceAudio: "/old" })).toEqual({ clone_voice: false });
  });
  it("selects the full model and omits builtin voice when cloning", () => {
    const form = { ...defaults(CONFIG, 2), voiceMode: "clone" as const, referenceAudio: "/clips/speaker.wav", referenceText: "Private words" };
    const result = requests("book.pdf", form, null).convert;
    expect(result.command === "convert" && result.convert).toMatchObject({ tts_provider: "kitten", tts_model: "kitten2", voice: null, clone_voice: true, reference_text: "Private words" });
    expect(validate({ ...form, referenceAudio: "" }, 2)).toHaveProperty("referenceAudio");
  });
  it("replacing a recording clears the old transcript and reports missing ASR", async () => {
    render(<Harness />);
    expect(screen.getByLabelText("Reference transcript (optional)")).toHaveValue("Old words");
    fireEvent.click(screen.getByText("Choose recording"));
    await waitFor(() => expect(screen.getByLabelText("Reference transcript (optional)")).toHaveValue(""));
    expect(await screen.findByText(/Add a transcript or set up local Whisper/)).toBeInTheDocument();
  });
  it("requires an explicit download confirmation", async () => {
    const download = vi.fn();
    render(<CloneControls form={{ voiceMode: "clone", referenceAudio: "/clip" }} onChange={() => undefined} onDownload={download} />);
    fireEvent.click(await screen.findByText("Set up KittenTTS 2"));
    expect(download).not.toHaveBeenCalled();
    expect(screen.getByText(/Pinned revisions and checksums/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Download model"));
    expect(download).toHaveBeenCalledOnce();
  });
});

it("inherits book profiles above global defaults without passing private placeholders", () => {
  const config = { ...CONFIG, tts: { ...CONFIG.tts, profiles: { Book: { clone_voice: true, kitten_model: "kitten2", reference_audio: "***" } }, voice_clone: { enabled: false, reference_audio: "***", reference_text_file: "***" } } };
  const form = defaults(config, 2, {}, false, "/books/Book.pdf");
  expect(form.inheritedClone).toBe(true);
  expect(form.inheritedReference).toBe(true);
  expect(form.inheritedTranscript).toBe(false);
  expect(cloneRequest(form)).toEqual({});
  const request = requests("/books/Book.pdf", form, null).convert;
  expect(JSON.stringify(request)).not.toContain("***");
  expect(request.command === "convert" && request.convert.voice).toBeNull();
});

it("keeps keyboard focus on the transcript and associates validation feedback", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  const transcript = screen.getByLabelText("Reference transcript (optional)");
  await user.click(transcript);
  await user.keyboard("{Control>}a{/Control}{Backspace}New spoken words");
  expect(transcript).toHaveFocus();
  expect(transcript).toHaveValue("New spoken words");
  fireEvent.change(transcript, { target: { value: "bad" + String.fromCharCode(0) + "text" } });
  expect(transcript).toHaveFocus();
  expect(transcript).toHaveAttribute("aria-invalid", "true");
  expect(document.getElementById(transcript.getAttribute("aria-describedby") ?? "")).toHaveTextContent("Remove NUL characters");
});

it("offers the voice cloning add-on in place when its packages are missing", async () => {
  const { run } = await import("../engine/api");
  vi.mocked(run).mockImplementation((async (request: { command: string }) => {
    if (request.command === "tts_models") {
      return { outcome: "success", result: { models: [{ name: "kitten2", ready: false, package_installed: false, weights_present: false, download_bytes: 1600000000, directory: "/model-cache", transcription_ready: false }] } };
    }
    if (request.command === "addons_list") {
      return { outcome: "success", result: { available: true, addons: [{ name: "kitten2", title: "Voice cloning and Kitten 2", installed: false, components: [], older_version_installed: false }] } };
    }
    throw new Error(`unexpected ${request.command}`);
  }) as never);
  render(<CloneControls form={{ voiceMode: "clone", referenceAudio: "/clip" }} onChange={() => undefined} />);
  expect(await screen.findByText(/needs the Voice cloning and Kitten 2 add-on/)).toBeInTheDocument();
  expect(screen.queryByText(/CLI environment/)).toBeNull();
  fireEvent.click(screen.getByText("Install voice cloning…"));
  expect(document.querySelector("md-dialog[open]")).toHaveTextContent("Install Voice cloning and Kitten 2?");
});
