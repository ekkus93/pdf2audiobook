import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AddonLanguages, AddonsList, Request } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(),
}));

import * as api from "../engine/api";
import { AddonDialog, AddonsPanel, OcrLanguages } from "./Addons";

const LIST: AddonsList = {
  available: true,
  addons: [
    {
      name: "kitten2",
      title: "Voice cloning and Kitten 2",
      installed: false,
      components: [
        { name: "audio-check+kitten2", installed: false, packages: 16 },
        { name: "kitten2", installed: false, packages: 35 },
      ],
      older_version_installed: false,
    },
    {
      name: "audio-check",
      title: "Audio checking (speech recognizers)",
      installed: true,
      components: [
        { name: "audio-check", installed: true, packages: 6 },
        { name: "audio-check+kitten2", installed: true, packages: 16 },
      ],
      older_version_installed: false,
    },
  ],
};
const LANGUAGES: AddonLanguages = { available: ["deu", "eng", "fra"], installed: ["eng"], bundled: ["eng"] };

function button(text: string, root: ParentNode = document): HTMLElement {
  const found = Array.from(root.querySelectorAll("md-filled-button, md-filled-tonal-button, md-outlined-button, md-text-button")).find(
    (element) => element.textContent?.includes(text),
  );
  if (!found) throw new Error(`no button labelled ${text}`);
  return found as HTMLElement;
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new Event("click", { bubbles: true }));
  });
}

let list: AddonsList;
let languages: AddonLanguages;
beforeEach(() => {
  list = structuredClone(LIST);
  languages = structuredClone(LANGUAGES);
  vi.mocked(api.run).mockImplementation(async (request: Request) => {
    if (request.command === "addons_list") return { outcome: "success", result: list };
    if (request.command === "addons_install") {
      list.addons[0].installed = true;
      return { outcome: "success", result: { addon: list.addons[0] } };
    }
    if (request.command === "addons_remove") {
      list.addons[1].installed = false;
      return { outcome: "success", result: { addon: list.addons[1] } };
    }
    if (request.command === "addon_languages") return { outcome: "success", result: languages };
    if (request.command === "addon_add_languages") {
      languages.installed = [...languages.installed, ...request.languages].sort();
      return { outcome: "success", result: languages };
    }
    if (request.command === "addon_remove_language") {
      languages.installed = languages.installed.filter((code) => code !== request.language);
      return { outcome: "success", result: languages };
    }
    throw new Error(`unexpected ${request.command}`);
  });
});

describe("AddonDialog", () => {
  it("says what is downloaded, from where and how much before asking", async () => {
    const onInstalled = vi.fn();
    render(<AddonDialog addon="kitten2" open onClose={vi.fn()} onInstalled={onInstalled} />);
    const dialog = document.querySelector("md-dialog[open]") as HTMLElement;
    expect(dialog).toHaveTextContent("Voice cloning and Kitten 2");
    expect(dialog).toHaveTextContent(/PyTorch/);
    expect(dialog).toHaveTextContent(/Hugging Face/);
    expect(dialog).toHaveTextContent(/about 3\.2 GB/);
    expect(api.run).not.toHaveBeenCalledWith(expect.objectContaining({ command: "addons_install" }));
    await click(button("Download and install", dialog));
    expect(api.run).toHaveBeenCalledWith({ command: "addons_install", addon: "kitten2" });
    await waitFor(() => expect(onInstalled).toHaveBeenCalled());
  });

  it("shows why an install failed and lets the user try again", async () => {
    vi.mocked(api.run).mockResolvedValueOnce({
      outcome: "failed",
      error: { type: "AudioError", code: 6, message: "The add-on could not be installed. Check the network connection and try again" },
      warnings: [],
    });
    render(<AddonDialog addon="audio-check" open onClose={vi.fn()} onInstalled={vi.fn()} />);
    const dialog = document.querySelector("md-dialog[open]") as HTMLElement;
    await click(button("Download and install", dialog));
    expect(await screen.findByText(/Check the network connection/)).toBeInTheDocument();
    expect(button("Download and install", dialog)).not.toHaveAttribute("disabled");
  });
});

describe("AddonsPanel", () => {
  it("lists each add-on with an install or remove action", async () => {
    render(<AddonsPanel />);
    expect(await screen.findByText("Voice cloning and Kitten 2")).toBeInTheDocument();
    expect(screen.getByText("Audio checking (speech recognizers)")).toBeInTheDocument();
    await click(button("Install…"));
    expect(document.querySelector("md-dialog[open]")).toHaveTextContent("Voice cloning and Kitten 2");
    await click(button("Remove"));
    expect(api.run).toHaveBeenCalledWith({ command: "addons_remove", addon: "audio-check" });
    await waitFor(() => expect(screen.getAllByText(/^Not installed/)).toHaveLength(2));
  });

  it("shows nothing outside the built-in engine", async () => {
    list = { available: false, addons: [] };
    const { container } = render(<AddonsPanel />);
    await waitFor(() => expect(api.run).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("says when add-ons for an older version are no longer used", async () => {
    list.addons.forEach((addon) => (addon.older_version_installed = true));
    render(<AddonsPanel />);
    expect(await screen.findByText(/installed for an earlier version/)).toBeInTheDocument();
  });
});

describe("OcrLanguages", () => {
  it("adds a language and removes only added ones", async () => {
    render(<OcrLanguages />);
    expect(await screen.findByText("eng")).toBeInTheDocument();
    const select = Array.from(document.querySelectorAll("md-outlined-select")).find(
      (element) => (element as HTMLElement & { label: string }).label === "Add a language",
    ) as HTMLElement & { value: string };
    await act(async () => {
      Object.defineProperty(select, "value", { value: "deu", writable: true, configurable: true });
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await click(button("Download"));
    expect(api.run).toHaveBeenCalledWith({ command: "addon_add_languages", languages: ["deu"] });
    expect(await screen.findByText("deu")).toBeInTheDocument();
    expect(document.querySelector('[aria-label="Remove eng"]')).toBeNull();
    await click(document.querySelector('[aria-label="Remove deu"]') as HTMLElement);
    expect(api.run).toHaveBeenCalledWith({ command: "addon_remove_language", language: "deu" });
  });
});
