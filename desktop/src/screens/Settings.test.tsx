import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppSettings, Request } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(),
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
// The setup check has its own tests (Setup.test.tsx).
vi.mock("./Setup", () => ({ Setup: () => <p>The setup check</p> }));

import { open } from "@tauri-apps/plugin-dialog";
import * as api from "../engine/api";
import { CONFIG } from "./bookOptions.test";
import { Settings, VOICE_SAMPLES, configRows, sourceLabel } from "./Settings";

const SAVED: AppSettings = {
  cli_path: null,
  uv_project: null,
  output_dir: null,
  theme: "dark",
  added_books: ["/books/a.pdf"],
  default_voice: null,
  llm_provider: null,
  llm_model: null,
};

const SOURCES = {
  "general.output_dir": "file:/home/me/.config/pdf2audiobook/config.toml",
  "llm.provider": "env:PDF2AUDIOBOOK_LLM_PROVIDER",
};

beforeEach(() => {
  vi.mocked(api.getSettings).mockResolvedValue(SAVED);
  vi.mocked(api.saveSettings).mockResolvedValue(undefined);
  vi.mocked(api.run).mockImplementation(async (request: Request) => {
    if (request.command === "config_show") {
      return { outcome: "success", result: { ...CONFIG, _sources: SOURCES, warnings: [] } };
    }
    if (request.command === "voices") {
      return { outcome: "success", result: { provider: "kitten", voices: ["Bella", "Jasper", "Luna"], listable: true, default_voice: "Jasper" } };
    }
    throw new Error(`unexpected ${request.command}`);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
});

async function ready() {
  render(<Settings />);
  await screen.findByRole("table", { name: "CLI configuration" });
}

type Labelled = HTMLElement & { value: string; label: string; supportingText?: string };

/** React sets `label` as a property on Material elements, not as an attribute. */
function byLabel(tag: string, label: string): Labelled {
  const found = Array.from(document.querySelectorAll(tag)).find((element) => (element as Labelled).label === label);
  if (!found) throw new Error(`no ${tag} labelled ${label}`);
  return found as Labelled;
}

const field = (label: string) => byLabel("md-outlined-text-field", label);
const select = (label: string) => byLabel("md-outlined-select", label);

async function type(label: string, value: string) {
  const element = field(label);
  await act(async () => {
    element.value = value;
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function choose(label: string, value: string) {
  const element = select(label);
  const spy = vi.spyOn(Object.getPrototypeOf(element), "value", "get").mockReturnValue(value);
  await act(async () => {
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
  spy.mockRestore();
}

function button(text: string, scope: ParentNode = document): HTMLElement {
  const found = Array.from(scope.querySelectorAll("md-filled-button, md-filled-tonal-button, md-text-button")).find(
    (element) => element.textContent?.trim() === text || element.textContent?.includes(text),
  );
  if (!found) throw new Error(`no button labelled ${text}`);
  return found as HTMLElement;
}

async function press(element: HTMLElement) {
  await act(async () => {
    element.dispatchEvent(new Event("click", { bubbles: true }));
  });
}

describe("configRows", () => {
  it("flattens the configuration with each value's source, leaving out the bookkeeping", () => {
    const rows = configRows({ ...CONFIG, _sources: SOURCES });
    expect(rows.find((row) => row.key === "general.output_dir")).toEqual({
      key: "general.output_dir",
      value: CONFIG.general.output_dir,
      source: "Config file (/home/me/.config/pdf2audiobook/config.toml)",
    });
    expect(rows.find((row) => row.key === "llm.provider")?.source).toBe("Environment (PDF2AUDIOBOOK_LLM_PROVIDER)");
    expect(rows.find((row) => row.key === "llm.max_context_tokens")).toEqual({
      key: "llm.max_context_tokens",
      value: String(CONFIG.llm.max_context_tokens),
      source: "Built-in default",
    });
    expect(rows.some((row) => row.key.startsWith("_sources") || row.key.startsWith("warnings"))).toBe(false);
  });

  it("shows null as a dash", () => {
    expect(configRows({ ...CONFIG, general: { ...CONFIG.general, extra: null } as never })).toContainEqual({
      key: "general.extra",
      value: "—",
      source: "Built-in default",
    });
  });

  it.each([
    [undefined, "Built-in default"],
    ["built-in", "Built-in default"],
    ["cli", "cli"],
  ])("labels source %s as %s", (source, label) => {
    expect(sourceLabel(source)).toBe(label);
  });
});

describe("Settings", () => {
  it("shows the app's settings with the CLI's values as the defaults", async () => {
    await ready();
    expect(field("CLI location").value).toBe("");
    expect(field("Output folder").supportingText).toBe(`Empty uses the CLI's output folder: ${CONFIG.general.output_dir}.`);
    expect(select("Voice").value).toBe("");
    expect(select("Voice")).toHaveTextContent(`The CLI's voice (${CONFIG.tts.kitten.voice})`);
    expect(select("Provider")).toHaveTextContent(`The CLI's provider (${CONFIG.llm.provider})`);
    expect(screen.getByText("The setup check")).toBeInTheDocument();
    expect(button("Save settings")).toHaveAttribute("disabled");
  });

  it("saves only the app's settings file, keeping what it doesn't edit, and applies the theme", async () => {
    await ready();
    await type("CLI location", " /opt/pdf2audiobook/bin/pdf2audiobook ");
    await type("Output folder", "/books/out");
    await choose("Voice", "Luna");
    await choose("Provider", "llama-server");
    await type("Model", "local-model");
    await choose("Theme", "light");
    expect(button("Save settings")).not.toHaveAttribute("disabled");
    await press(button("Save settings"));
    expect(api.saveSettings).toHaveBeenCalledWith({
      ...SAVED,
      cli_path: "/opt/pdf2audiobook/bin/pdf2audiobook",
      output_dir: "/books/out",
      default_voice: "Luna",
      llm_provider: "llama-server",
      llm_model: "local-model",
      theme: "light",
    });
    expect(api.run).not.toHaveBeenCalledWith(expect.objectContaining({ command: expect.stringMatching(/^config_(set|edit)/) }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(await screen.findByText("Saved. New books and runs use these settings.")).toBeInTheDocument();
    expect(button("Save settings")).toHaveAttribute("disabled");
  });

  it("clearing a field goes back to the CLI's value", async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ ...SAVED, output_dir: "/books/out", default_voice: "Luna" });
    await ready();
    await type("Output folder", "  ");
    await choose("Voice", "");
    await press(button("Save settings"));
    expect(api.saveSettings).toHaveBeenCalledWith({ ...SAVED, output_dir: null, default_voice: null });
  });

  it("browses for the CLI and the output folder", async () => {
    await ready();
    vi.mocked(open).mockResolvedValueOnce("/opt/cli").mockResolvedValueOnce("/books/out").mockResolvedValueOnce(null);
    const browse = Array.from(document.querySelectorAll("md-text-button")).filter((element) =>
      element.textContent?.includes("Browse"),
    ) as HTMLElement[];
    await press(browse[0]);
    expect(open).toHaveBeenLastCalledWith({ multiple: false, directory: false });
    await press(browse[2]);
    expect(open).toHaveBeenLastCalledWith({ multiple: false, directory: true });
    await press(browse[1]);
    expect(field("CLI location").value).toBe("/opt/cli");
    expect(field("Output folder").value).toBe("/books/out");
    expect(field("Source checkout").value).toBe("");
  });

  it("plays the README's sample of a voice", async () => {
    expect(Object.keys(VOICE_SAMPLES).sort()).toEqual(["Bella", "Bruno", "Hugo", "Jasper", "Kiki", "Leo", "Luna", "Rosie"]);
    const fetched: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      fetched.push(url);
      return new Response(new Blob(["mp3"], { type: "audio/mpeg" }));
    });
    URL.createObjectURL = () => "blob:sample";
    URL.revokeObjectURL = () => undefined;
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    await ready();
    const samples = screen.getByRole("list", { name: "Voice samples" });
    await press(button("Luna", samples));
    expect(fetched).toEqual([VOICE_SAMPLES.Luna]);
    expect((screen.getByTestId("voice-sample") as HTMLAudioElement).src).toBe("blob:sample");
    expect(play).toHaveBeenCalled();
  });

  it("says when a sample can't be played", async () => {
    vi.stubGlobal("fetch", async () => new Response(null, { status: 404 }));
    await ready();
    await press(button("Bella", screen.getByRole("list", { name: "Voice samples" })));
    expect(await screen.findByText("The sample couldn't be played")).toBeInTheDocument();
  });

  it("shows the CLI configuration read-only with where each value comes from", async () => {
    await ready();
    const table = screen.getByRole("table", { name: "CLI configuration" });
    const row = within(table).getByText("general.output_dir").closest("tr") as HTMLElement;
    expect(row).toHaveTextContent(CONFIG.general.output_dir);
    expect(row).toHaveTextContent("Config file (/home/me/.config/pdf2audiobook/config.toml)");
    expect(table.querySelector("input, md-outlined-text-field")).toBeNull();
    expect(screen.getByText("~/.config/pdf2audiobook/config.toml")).toBeInTheDocument();
  });

  it("still edits the app's settings when the CLI can't be reached", async () => {
    vi.mocked(api.run).mockRejectedValue({ kind: "locate", message: "pdf2audiobook was not found" });
    render(<Settings />);
    expect(await screen.findByText("pdf2audiobook was not found")).toBeInTheDocument();
    expect(field("CLI location")).toBeInTheDocument();
    expect(select("Voice")).toHaveTextContent("The CLI's voice");
    expect(screen.queryByRole("table", { name: "CLI configuration" })).not.toBeInTheDocument();
  });

  it("reports settings that couldn't be saved", async () => {
    vi.mocked(api.saveSettings).mockRejectedValue({ kind: "request", message: "The settings could not be saved" });
    await ready();
    await choose("Theme", "system");
    await press(button("Save settings"));
    expect(await screen.findByText("The settings could not be saved")).toBeInTheDocument();
    await waitFor(() => expect(button("Save settings")).not.toHaveAttribute("disabled"));
  });
});
