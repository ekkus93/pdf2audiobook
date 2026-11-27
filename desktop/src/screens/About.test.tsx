import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Notice } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  engineNotices: vi.fn(),
  engineNoticeText: vi.fn(),
}));

import * as api from "../engine/api";
import { About } from "./About";

const NOTICES: Notice[] = [
  {
    name: "FFmpeg",
    version: "8.1.3",
    license: "LGPL-2.1-or-later",
    source: "https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz",
    files: ["share/licenses/ffmpeg/COPYING.LGPLv2.1"],
  },
  {
    name: "espeak-ng",
    version: "1.52.0",
    license: "GPL-3.0-or-later",
    source: "https://github.com/espeak-ng/espeak-ng/tree/4870adf",
    files: ["share/licenses/espeak-ng/COPYING"],
  },
];

function button(text: string): HTMLElement {
  const found = Array.from(document.querySelectorAll("md-text-button")).filter((element) => element.textContent?.includes(text));
  if (!found.length) throw new Error(`no button labelled ${text}`);
  return found[found.length - 1] as HTMLElement;
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new Event("click", { bubbles: true }));
  });
}

beforeEach(() => {
  vi.mocked(api.engineNotices).mockResolvedValue(NOTICES);
  vi.mocked(api.engineNoticeText).mockResolvedValue("==> share/licenses/espeak-ng/COPYING <==\nGNU GENERAL PUBLIC LICENSE");
});

describe("About", () => {
  it("lists each bundled component with its licence and source", async () => {
    render(<About />);
    expect(await screen.findByText("FFmpeg 8.1.3")).toBeInTheDocument();
    expect(screen.getByText("GPL-3.0-or-later")).toBeInTheDocument();
    expect(screen.getByText(/Source: https:\/\/ffmpeg\.org\/releases/)).toBeInTheDocument();
    expect(screen.getByText(/these 2 components/)).toBeInTheDocument();
  });

  it("shows a component's licence text", async () => {
    render(<About />);
    await screen.findByText("espeak-ng 1.52.0");
    const licences = Array.from(document.querySelectorAll("md-text-button")).filter((element) => element.textContent?.includes("Licence"));
    await click(licences[1]);
    expect(api.engineNoticeText).toHaveBeenCalledWith(1);
    expect(await screen.findByText(/GNU GENERAL PUBLIC LICENSE/)).toBeInTheDocument();
    expect(document.querySelector("md-dialog[open]")).toHaveTextContent("espeak-ng licence");
    await click(button("Close"));
    expect(document.querySelector("md-dialog[open]")).toBeNull();
  });

  it("says when a licence text cannot be read", async () => {
    vi.mocked(api.engineNoticeText).mockRejectedValue({ kind: "request", message: "The licence text could not be read; reinstall the app" });
    render(<About />);
    await screen.findByText("FFmpeg 8.1.3");
    await click(button("Licence"));
    expect(await screen.findByRole("alert")).toHaveTextContent("reinstall the app");
  });

  it("lists nothing in a build without a built-in engine", async () => {
    vi.mocked(api.engineNotices).mockResolvedValue(null);
    render(<About />);
    expect(await screen.findByText(/Apache License 2\.0/)).toBeInTheDocument();
    await act(async () => undefined);
    expect(document.querySelector(".notice-list")).toBeNull();
  });
});
