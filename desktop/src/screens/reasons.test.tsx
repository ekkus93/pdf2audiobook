import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Progress, Request } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  runProgress: vi.fn(),
  cancelRun: vi.fn(),
  run: vi.fn(),
}));

import * as api from "../engine/api";
import { CONFIG } from "./bookOptions.test";
import { Run } from "./Run";
import { ACTION_REASONS, unacknowledged } from "./reasons";

const CONVERT: Request = {
  command: "convert",
  book: "/books/lighthouse.pdf",
  options: { output: "/out" },
  convert: { voice: "Jasper", accept_review: [] },
};

const RUN = {
  id: 7,
  title: "The Lighthouse at Gull Point",
  command: "convert" as const,
  workspace: "/out/lighthouse-1",
  manifest: "/out/lighthouse-1/manifest.json",
  request: CONVERT,
};

function stoppedWith(reason: string, message = `stopped: ${reason}`): Progress {
  return {
    state: "finished",
    status: null,
    outcome: { outcome: "failed", error: { type: "AudioError", code: 6, message, reason }, warnings: [] },
    cancelled: false,
  };
}

function setup(reason: string, message?: string, waitingForLock = false) {
  vi.mocked(api.runProgress).mockResolvedValue(stoppedWith(reason, message));
  const handlers = { onRestart: vi.fn(), onOpenSettings: vi.fn(), onDone: vi.fn(), onReview: vi.fn() };
  render(<Run run={{ ...RUN, waitingForLock }} pollMs={5} lockRetrySeconds={0.01} {...handlers} />);
  return handlers;
}

function button(text: string): HTMLElement {
  const found = Array.from(
    document.querySelectorAll("md-filled-button, md-filled-tonal-button, md-outlined-button, md-text-button"),
  ).find((element) => element.textContent?.includes(text));
  if (!found) throw new Error(`no button labelled ${text}`);
  return found as HTMLElement;
}

async function press(text: string) {
  await act(async () => {
    button(text).dispatchEvent(new Event("click", { bubbles: true }));
  });
}

beforeEach(() => {
  vi.mocked(api.cancelRun).mockResolvedValue(undefined);
});

describe("every D2.b reason leads to its action", () => {
  it("covers all stable reasons between this file and Run.test.tsx", () => {
    // review_required and pending_recovery are tested in Run.test.tsx.
    expect([...ACTION_REASONS, "review_required", "pending_recovery"].sort()).toEqual(
      [
        "budget_exhausted",
        "chapter_conflict",
        "llm_context_too_small",
        "llm_output_cap",
        "llm_unreachable",
        "pending_recovery",
        "review_acknowledgement_required",
        "review_required",
        "workspace_locked",
        "voice_clone_unsupported", "voice_clone_unavailable", "voice_reference_invalid", "voice_reference_changed", "voice_selection_conflict",
      ].sort(),
    );
  });

  it("review_acknowledgement_required: shows the reasons and converts again acknowledging them", async () => {
    vi.mocked(api.run).mockResolvedValue({
      outcome: "success",
      result: {
        title: "Book",
        source_path: "/books/lighthouse.pdf",
        review_required: ["damaged_source", "ambiguous_page_numbers", "low_confidence"],
        review_acknowledged: ["ambiguous_page_numbers"],
        approved: false,
        chapters: [],
      },
    });
    const { onRestart, onReview } = setup("review_acknowledgement_required");
    expect(await screen.findByText("This book needs your acknowledgement before converting")).toBeInTheDocument();
    expect(await screen.findByText("damaged_source")).toBeInTheDocument();
    expect(screen.queryByText("ambiguous_page_numbers")).not.toBeInTheDocument();
    expect(api.run).toHaveBeenCalledWith({ command: "inspect", source: RUN.manifest });
    await waitFor(() => expect(onReview).toHaveBeenCalledOnce());
    await press("Acknowledge and convert");
    expect(onRestart).toHaveBeenCalledWith({ ...CONVERT, convert: { ...CONVERT.convert, accept_review: ["damaged_source"] } });
  });

  it("workspace_locked: offers to wait, retrying until it's free, or to cancel", async () => {
    const { onRestart, onDone } = setup("workspace_locked");
    expect(await screen.findByText("Another task is using this book")).toBeInTheDocument();
    await press("Cancel");
    expect(onDone).toHaveBeenCalledOnce();
    await press("Wait and try again");
    await waitFor(() => expect(onRestart).toHaveBeenCalledWith(CONVERT, { waitForLock: true }));
  });

  it("workspace_locked while already waiting: keeps waiting by itself until cancelled", async () => {
    const { onRestart } = setup("workspace_locked", undefined, true);
    expect(await screen.findByText(/Waiting for it to finish/)).toBeInTheDocument();
    await waitFor(() => expect(onRestart).toHaveBeenCalledWith(CONVERT, { waitForLock: true }));
  });

  it("workspace_locked: cancelling the wait stops the retries", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.mocked(api.runProgress).mockResolvedValue(stoppedWith("workspace_locked"));
      const onRestart = vi.fn();
      render(<Run run={{ ...RUN, waitingForLock: true }} pollMs={5} lockRetrySeconds={5} onRestart={onRestart} />);
      await screen.findByText(/Waiting for it to finish/);
      await press("Cancel");
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      expect(onRestart).not.toHaveBeenCalled();
      expect(screen.getByText(/this task starts by itself, or cancel/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("chapter_conflict: regenerates the chapter with a backup, then runs again", async () => {
    vi.mocked(api.run).mockResolvedValue({
      outcome: "success",
      result: { regenerated: [3], backed_up: ["/out/lighthouse-1/chapters/003.txt.bak-1"] },
    });
    const { onRestart } = setup(
      "chapter_conflict",
      "Chapter 3 text conflicts with generated content; run pdf2audiobook regenerate-chapter on the manifest with --chapter 3",
    );
    expect(await screen.findByText("The text file for chapter 3 was edited")).toBeInTheDocument();
    await press("Regenerate chapter 3 with a backup");
    expect(api.run).toHaveBeenCalledWith(
      { command: "regenerate_chapter", manifest: RUN.manifest, which: { kind: "chapter", chapter: 3 } },
      RUN.workspace,
    );
    expect(await screen.findByText("Regenerated. Your edited file was kept as 003.txt.bak-1.")).toBeInTheDocument();
    await press("Run again");
    expect(onRestart).toHaveBeenCalledWith(CONVERT);
  });

  it("chapter_conflict without a chapter number regenerates every conflict", async () => {
    vi.mocked(api.run).mockResolvedValue({ outcome: "success", result: { regenerated: [1, 2], backed_up: [] } });
    setup("chapter_conflict", "Chapter text conflicts");
    expect(await screen.findByText("The text file for the conflicting chapters was edited")).toBeInTheDocument();
    await press("Regenerate the conflicting chapters with a backup");
    expect(api.run).toHaveBeenCalledWith(
      { command: "regenerate_chapter", manifest: RUN.manifest, which: { kind: "all_conflicts" } },
      RUN.workspace,
    );
  });

  it("llm_unreachable: links to the LLM settings", async () => {
    const { onOpenSettings } = setup("llm_unreachable");
    expect(await screen.findByText("The LLM server couldn't be reached")).toBeInTheDocument();
    await press("Open LLM settings");
    expect(onOpenSettings).toHaveBeenCalledOnce();
  });

  it("llm_context_too_small: explains num_ctx and the context setting", async () => {
    const { onDone } = setup("llm_context_too_small");
    const panel = await screen.findByRole("region", { name: "LLM context too small" });
    expect(panel).toHaveTextContent("num_ctx");
    expect(panel).toHaveTextContent("Context (tokens)");
    await press("Change the context");
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("llm_output_cap: suggests a larger output cap", async () => {
    const { onDone } = setup("llm_output_cap");
    const panel = await screen.findByRole("region", { name: "LLM output cap" });
    expect(panel).toHaveTextContent("Output cap (tokens)");
    expect(panel).toHaveTextContent("32768");
    await press("Change the output cap");
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("budget_exhausted: shows the budget against its limits", async () => {
    vi.mocked(api.run).mockImplementation(async (request: Request) => {
      if (request.command === "budget_show") {
        return {
          outcome: "success",
          result: {
            requests: [],
            totals: { requests_started: 120, unresolved_requests: 2, reported_tokens: 345678, estimated_cost_usd: 0 },
            warnings: [],
          },
        };
      }
      if (request.command === "config_show") {
        return { outcome: "success", result: { ...CONFIG, llm: { ...CONFIG.llm, max_requests: 120, max_reported_tokens: null } } };
      }
      throw new Error(`unexpected ${request.command}`);
    });
    const { onRestart } = setup("budget_exhausted");
    const table = await screen.findByRole("table", { name: "LLM budget" });
    expect(api.run).toHaveBeenCalledWith({ command: "budget_show", workspace: RUN.workspace });
    expect(table.querySelectorAll("tbody tr")[0]).toHaveTextContent("Requests120120");
    expect(table.querySelectorAll("tbody tr")[1]).toHaveTextContent("Reported tokens345,678no limit");
    expect(screen.getByText(/2 request\(s\) never reported their usage/)).toBeInTheDocument();
    await press("Run again");
    expect(onRestart).toHaveBeenCalledWith(CONVERT);
  });

  it("budget_exhausted: shows why the budget couldn't be read", async () => {
    vi.mocked(api.run).mockResolvedValue({
      outcome: "failed",
      error: { type: "ConfigError", code: 2, message: "Per-book LLM budget ledger does not exist" },
      warnings: [],
    });
    setup("budget_exhausted");
    expect(await screen.findByText("Per-book LLM budget ledger does not exist")).toBeInTheDocument();
  });

  it("a failure without a reason offers no action", async () => {
    vi.mocked(api.runProgress).mockResolvedValue({
      state: "finished",
      status: null,
      outcome: { outcome: "failed", error: { type: "AudioError", code: 6, message: "No audio" }, warnings: [] },
      cancelled: false,
    });
    render(<Run run={RUN} pollMs={5} onRestart={vi.fn()} />);
    await screen.findByText("No audio");
    expect(document.querySelectorAll("section.recover")).toHaveLength(0);
  });
});

describe("unacknowledged", () => {
  it("keeps only book-wide reasons not yet acknowledged", () => {
    expect(
      unacknowledged({
        title: "",
        source_path: "",
        review_required: ["damaged_source", "low_confidence", "ambiguous_page_numbers"],
        review_acknowledged: ["damaged_source"],
        approved: false,
        chapters: [],
      }),
    ).toEqual(["ambiguous_page_numbers"]);
  });
});

it.each(["voice_clone_unsupported", "voice_clone_unavailable", "voice_reference_invalid", "voice_reference_changed", "voice_selection_conflict"])("%s directs the user back to voice options", async (reason) => {
  const { onDone } = setup(reason);
  expect(await screen.findByText("Check the voice selection")).toBeInTheDocument();
  await press("Change voice options");
  expect(onDone).toHaveBeenCalledOnce();
});
