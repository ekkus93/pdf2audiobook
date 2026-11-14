import { act, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PendingEdit, Request } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(),
}));

import * as api from "../engine/api";
import { PendingEdits } from "./PendingEdits";

const MANIFEST = "/out/book-1/manifest.json";
const WORKSPACE = "/out/book-1";
const EDITS: PendingEdit[] = [
  { block_id: "p00003-l00012", chapter: 2, provider: "ollama", status: "pending", reason: "OCR split a word", original: "the light house", replacement: "the lighthouse" },
  { block_id: "p00004-l00001", chapter: 3, provider: "ollama", status: "pending", reason: "spoken form", original: "x² + 1", replacement: "x squared plus one" },
];

let pending: PendingEdit[] = [];

beforeEach(() => {
  pending = [...EDITS];
  vi.mocked(api.run).mockImplementation(async (request: Request) => {
    if (request.command === "edits_list") return { outcome: "success", result: { edits: pending } };
    if (request.command === "edits_accept" || request.command === "edits_reject") {
      const ids = request.which.kind === "all" ? pending.map((edit) => edit.block_id) : request.which.ids;
      pending = pending.filter((edit) => !ids.includes(edit.block_id));
      return { outcome: "success", result: {} };
    }
    throw new Error(`unexpected ${request.command}`);
  });
});

function button(scope: ParentNode, text: string): HTMLElement {
  const found = Array.from(scope.querySelectorAll("md-filled-button, md-filled-tonal-button, md-text-button")).find(
    (element) => element.textContent?.includes(text),
  );
  if (!found) throw new Error(`no button labelled ${text}`);
  return found as HTMLElement;
}

async function press(element: HTMLElement) {
  await act(async () => {
    element.dispatchEvent(new Event("click", { bubbles: true }));
  });
}

describe("PendingEdits", () => {
  it("lists each edit with its original and proposed text", async () => {
    render(<PendingEdits manifest={MANIFEST} workspace={WORKSPACE} />);
    expect(screen.getByRole("progressbar", { name: "Loading pending edits" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Edits" });
    const first = within(list).getByRole("listitem", { name: "Edit p00003-l00012" });
    expect(first).toHaveTextContent("Chapter 2 · ollama");
    expect(within(first).getByText("the light house").tagName).toBe("DEL");
    expect(within(first).getByText("the lighthouse").tagName).toBe("INS");
    expect(first).toHaveTextContent("OCR split a word");
    expect(api.run).toHaveBeenCalledWith({ command: "edits_list", manifest: MANIFEST, status: "pending", with_text: true });
  });

  it("says when nothing is waiting", async () => {
    pending = [];
    render(<PendingEdits manifest={MANIFEST} workspace={WORKSPACE} />);
    expect(await screen.findByText("No edits are waiting for you.")).toBeInTheDocument();
  });

  it("shows why the edits couldn't load", async () => {
    vi.mocked(api.run).mockResolvedValue({
      outcome: "failed",
      error: { type: "ExtractionError", code: 4, message: "Cannot read or validate audiobook manifest" },
      warnings: [],
    });
    render(<PendingEdits manifest={MANIFEST} workspace={WORKSPACE} />);
    expect(await screen.findByText("Cannot read or validate audiobook manifest")).toBeInTheDocument();
  });

  it("accepts or rejects one edit for the book's workspace", async () => {
    const onChanged = vi.fn();
    render(<PendingEdits manifest={MANIFEST} workspace={WORKSPACE} onChanged={onChanged} />);
    const list = await screen.findByRole("list", { name: "Edits" });
    await press(button(within(list).getByRole("listitem", { name: "Edit p00003-l00012" }), "Accept"));
    expect(api.run).toHaveBeenCalledWith(
      { command: "edits_accept", manifest: MANIFEST, which: { kind: "blocks", ids: ["p00003-l00012"] } },
      WORKSPACE,
    );
    await waitFor(() =>
      expect(screen.queryByRole("listitem", { name: "Edit p00003-l00012" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("listitem", { name: "Edit p00004-l00001" })).toBeInTheDocument();
    await press(button(screen.getByRole("listitem", { name: "Edit p00004-l00001" }), "Reject"));
    expect(api.run).toHaveBeenCalledWith(
      { command: "edits_reject", manifest: MANIFEST, which: { kind: "blocks", ids: ["p00004-l00001"] } },
      WORKSPACE,
    );
    expect(await screen.findByText("No edits are waiting for you.")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it("accepts all only after confirming the count", async () => {
    render(<PendingEdits manifest={MANIFEST} workspace={WORKSPACE} />);
    await screen.findByRole("list", { name: "Edits" });
    await press(button(document, "Accept all"));
    const dialog = document.querySelector("md-dialog") as HTMLElement & { open: boolean };
    expect(dialog.open).toBe(true);
    expect(dialog).toHaveTextContent("Accept all 2 edits?");
    await press(button(dialog, "Cancel"));
    expect(api.run).not.toHaveBeenCalledWith(expect.objectContaining({ command: "edits_accept" }), WORKSPACE);
    await press(button(document, "Accept all"));
    await press(button(dialog, "Accept 2"));
    expect(api.run).toHaveBeenCalledWith({ command: "edits_accept", manifest: MANIFEST, which: { kind: "all" } }, WORKSPACE);
    expect(await screen.findByText("No edits are waiting for you.")).toBeInTheDocument();
  });

  it("reports a decision the engine refused", async () => {
    vi.mocked(api.run).mockImplementation(async (request: Request) => {
      if (request.command === "edits_list") return { outcome: "success", result: { edits: EDITS } };
      return {
        outcome: "failed",
        error: { type: "ExtractionError", code: 4, message: "Multiple accepted edits for source block" },
        warnings: [],
      };
    });
    render(<PendingEdits manifest={MANIFEST} workspace={WORKSPACE} />);
    const list = await screen.findByRole("list", { name: "Edits" });
    await press(button(within(list).getByRole("listitem", { name: "Edit p00003-l00012" }), "Accept"));
    expect(await screen.findByText("Multiple accepted edits for source block")).toBeInTheDocument();
  });
});
