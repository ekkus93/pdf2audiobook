import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(async () => ({ outcome: "success", result: { models: [] } })),
  readCliConfig: vi.fn(),
  saveCliConfig: vi.fn(),
}));

import * as api from "../engine/api";
import { CliConfigEditor } from "./CliConfigEditor";

const FILE = { path: "/config/pdf2audiobook/config.toml", text: "# my settings\n[llm]\nenabled=true\n" };

beforeEach(() => {
  vi.mocked(api.readCliConfig).mockResolvedValue(FILE);
  vi.mocked(api.saveCliConfig).mockImplementation(async (text) => ({ ...FILE, text }));
});

describe("shared configuration editor", () => {
  it("loads the actual file and saves with its original contents for conflict detection", async () => {
    const onSaved = vi.fn();
    render(<CliConfigEditor onSaved={onSaved} />);
    const editor = await screen.findByRole("textbox", { name: "Configuration file (TOML)" });
    expect(editor).toHaveValue(FILE.text);
    expect(screen.getByText(FILE.path)).toBeInTheDocument();
    expect(screen.getByText("Save configuration")).toHaveAttribute("disabled");
    const next = FILE.text.replace("true", "false");
    fireEvent.change(editor, { target: { value: next } });
    fireEvent.click(screen.getByText("Save configuration"));
    await waitFor(() => expect(api.saveCliConfig).toHaveBeenCalledWith(next, FILE.text));
    expect(await screen.findByRole("status")).toHaveTextContent("Configuration saved");
    expect(onSaved).toHaveBeenCalledOnce();
    expect(screen.getByText("Save configuration")).toHaveAttribute("disabled");
  });

  it.each([
    "invalid TOML configuration syntax",
    "The configuration changed outside this editor. Reload it before saving.",
  ])("keeps unsaved text when saving fails: %s", async (message) => {
    vi.mocked(api.saveCliConfig).mockRejectedValue({ message });
    const onSaved = vi.fn();
    render(<CliConfigEditor onSaved={onSaved} />);
    const editor = await screen.findByRole("textbox", { name: "Configuration file (TOML)" });
    fireEvent.change(editor, { target: { value: "my unsaved draft" } });
    fireEvent.click(screen.getByText("Save configuration"));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(editor).toHaveValue("my unsaved draft");
    expect(onSaved).not.toHaveBeenCalled();
    vi.mocked(api.readCliConfig).mockResolvedValue({ ...FILE, text: "# changed externally" });
    fireEvent.click(screen.getByText("Reload from disk"));
    await waitFor(() => expect(editor).toHaveValue("# changed externally"));
  });

  it("allows retrying a failed initial read", async () => {
    vi.mocked(api.readCliConfig).mockRejectedValueOnce({ message: "The configuration file could not be read" });
    render(<CliConfigEditor onSaved={() => undefined} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Reload from disk"));
    expect(await screen.findByRole("textbox")).toHaveValue(FILE.text);
  });
});

it("persists clone defaults only after applying to the editor and explicitly saving", async () => {
  render(<CliConfigEditor onSaved={() => undefined} />);
  const editor = await screen.findByRole("textbox", { name: "Configuration file (TOML)" });
  const mode = Array.from(document.querySelectorAll("md-outlined-select")).find((element) => (element as HTMLElement & {label:string}).label === "Voice source");
  if (!mode) throw new Error("Voice source missing");
  Object.defineProperty(mode, "value", { value: "clone", writable: true, configurable: true });
  fireEvent.change(mode);
  await screen.findByText("Choose recording");
  const field = Array.from(document.querySelectorAll("md-outlined-text-field")).find((element) => (element as HTMLElement & {label:string}).label === "Reference recording");
  if (!field) throw new Error("Reference recording missing");
  Object.defineProperty(field, "value", { value: "/voices/a ' speaker.wav", writable: true, configurable: true });
  fireEvent.input(field);
  expect(screen.queryByLabelText("Reference transcript (optional)")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Apply voice defaults to editor"));
  expect(api.saveCliConfig).not.toHaveBeenCalled();
  expect((editor as HTMLTextAreaElement).value).toContain('reference_audio = "/voices/a \' speaker.wav"');
  expect((editor as HTMLTextAreaElement).value).toContain('model = "kitten2"');
  fireEvent.click(screen.getByText("Save configuration"));
  await waitFor(() => expect(api.saveCliConfig).toHaveBeenCalledOnce());
});
