import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Progress, RunStatus } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  runProgress: vi.fn(),
  cancelRun: vi.fn(),
  run: vi.fn(),
}));

import * as api from "../engine/api";
import { Run, duration } from "./Run";

const RUN = {
  id: 7,
  title: "The Lighthouse at Gull Point",
  command: "convert" as const,
  workspace: "/out/lighthouse-1",
  manifest: "/out/lighthouse-1/manifest.json",
};

function status(done: number, changes: Partial<RunStatus> = {}): RunStatus {
  return {
    command: "convert",
    state: "running",
    updated_at: "2026-11-14T11:20:43+00:00",
    elapsed_seconds: 60,
    stage: {
      name: "Synthesizing speech",
      detail: "chapter 8/24",
      unit: "char",
      done,
      total: 40057,
      elapsed_seconds: 60,
      estimated_remaining_seconds: 175,
    },
    completed_stages: [{ name: "Analyzing with the LLM", seconds: 442 }],
    ...changes,
  };
}

function sequence(...steps: Progress[]) {
  const mock = vi.mocked(api.runProgress);
  for (const step of steps.slice(0, -1)) mock.mockResolvedValueOnce(step);
  mock.mockResolvedValue(steps[steps.length - 1]);
}

beforeEach(() => {
  vi.mocked(api.cancelRun).mockResolvedValue(undefined);
});

describe("duration", () => {
  it.each([
    [45, "45s"],
    [252, "4m 12s"],
    [3780, "1h 03m"],
    [-3, "0s"],
  ])("%d seconds is %s", (seconds, text) => {
    expect(duration(seconds)).toBe(text);
  });
});

describe("Run", () => {
  it("says when nothing is running", () => {
    render(<Run run={null} />);
    expect(screen.getByRole("heading", { name: "Nothing is running" })).toBeInTheDocument();
    expect(api.runProgress).not.toHaveBeenCalled();
  });

  it("polls run_status and shows each step: stage, counts, elapsed time and estimate", async () => {
    sequence(
      { state: "running", status: null, cancelling: false },
      { state: "running", status: status(10408), cancelling: false },
      { state: "running", status: status(20970, { elapsed_seconds: 120 }), cancelling: false },
    );
    render(<Run run={RUN} pollMs={5} />);
    expect(screen.getByRole("heading", { name: RUN.title })).toBeInTheDocument();
    expect(screen.getByText("Converting to audio")).toBeInTheDocument();
    expect(await screen.findByText("10,408 of 40,057 characters")).toBeInTheDocument();
    // The last step stays on screen; check the details there.
    expect(await screen.findByText("20,970 of 40,057 characters")).toBeInTheDocument();
    expect(screen.getByText("Synthesizing speech")).toBeInTheDocument();
    expect(screen.getByText("chapter 8/24")).toBeInTheDocument();
    expect(screen.getByText("52%")).toBeInTheDocument();
    expect(screen.getByText("about 2m 55s left")).toBeInTheDocument();
    expect(screen.getByText("2m 00s elapsed")).toBeInTheDocument();
    expect(screen.getByText("Analyzing with the LLM")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Synthesizing speech" })).toHaveAttribute("aria-valuenow", "52");
  });

  it("says it is estimating until the first unit of work finishes", async () => {
    const early = status(0);
    if (early.stage) early.stage = { ...early.stage, estimated_remaining_seconds: null };
    sequence({ state: "running", status: early, cancelling: false });
    render(<Run run={RUN} pollMs={5} />);
    expect(await screen.findByText("estimating…")).toBeInTheDocument();
  });

  it("stops the run with Stop, and shows that it is stopping", async () => {
    // Like the bridge: the run reports "cancelling" only once Stop has been pressed.
    let stopping = false;
    vi.mocked(api.cancelRun).mockImplementation(async () => {
      stopping = true;
    });
    vi.mocked(api.runProgress).mockImplementation(async () => ({
      state: "running",
      status: status(100),
      cancelling: stopping,
    }));
    render(<Run run={RUN} pollMs={5} />);
    await screen.findByText("100 of 40,057 characters");
    const stop = document.querySelector("md-outlined-button") as HTMLElement;
    expect(stop).toHaveTextContent("Stop");
    act(() => {
      stop.dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(api.cancelRun).toHaveBeenCalledWith(7);
    expect(await screen.findByText("Stopping…")).toBeInTheDocument();
  });

  it("reports a finished conversion with its time", async () => {
    const onDone = vi.fn();
    sequence({
      state: "finished",
      status: { ...status(40057), state: "completed", elapsed_seconds: 252, stage: null },
      outcome: { outcome: "success", result: { mp3_files: [] } },
      cancelled: false,
    });
    render(<Run run={RUN} onDone={onDone} pollMs={5} />);
    expect(await screen.findByText("Conversion finished in 4m 12s")).toBeInTheDocument();
    act(() => {
      document.querySelector("md-filled-tonal-button")?.dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(onDone).toHaveBeenCalledOnce();
    expect(api.runProgress).toHaveBeenCalledTimes(1);
  });

  it("reports a stopped run", async () => {
    sequence({
      state: "finished",
      status: { ...status(100), state: "stopped" },
      outcome: { outcome: "failed", error: { type: "Interrupted", code: 130, message: "Interrupted" }, warnings: [] },
      cancelled: true,
    });
    render(<Run run={RUN} pollMs={5} />);
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(screen.getByText(/Finished chapters are kept/)).toBeInTheDocument();
  });

  it("shows an audio check as its own task, and stopping it keeps the audio", async () => {
    sequence(
      {
        state: "running",
        status: status(3, {
          command: "verify-audio",
          stage: { name: "Listening with whisper", detail: null, unit: "chapter", done: 3, total: 13, elapsed_seconds: 40, estimated_remaining_seconds: 130 },
          completed_stages: [],
        }),
        cancelling: false,
      },
      {
        state: "finished",
        status: null,
        outcome: { outcome: "failed", error: { type: "Interrupted", code: 130, message: "Interrupted" }, warnings: [] },
        cancelled: true,
      },
    );
    render(<Run run={{ ...RUN, command: "verify_audio" }} pollMs={5} />);
    expect(screen.getByText("Checking the audio")).toBeInTheDocument();
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(screen.getByText(/Chapters already checked are kept in the report; no audio was changed/)).toBeInTheDocument();
  });

  it("names a finished audio check and a stopped repair", async () => {
    sequence({
      state: "finished",
      status: { ...status(13), state: "completed", stage: null, elapsed_seconds: 185 },
      outcome: { outcome: "success", result: {} },
      cancelled: false,
    });
    const { unmount } = render(<Run run={{ ...RUN, command: "verify_audio" }} pollMs={5} />);
    expect(await screen.findByText("Audio check finished in 3m 05s")).toBeInTheDocument();
    unmount();
    sequence({
      state: "finished",
      status: null,
      outcome: { outcome: "failed", error: { type: "Interrupted", code: 130, message: "Interrupted" }, warnings: [] },
      cancelled: true,
    });
    render(<Run run={{ ...RUN, command: "resynthesize" }} pollMs={5} />);
    expect(screen.getByText("Speaking chapters again")).toBeInTheDocument();
    expect(await screen.findByText(/keeps its previous audio until its new audio is ready/)).toBeInTheDocument();
  });

  it("reports the engine's error, and a fixed message for an unreadable result", async () => {
    sequence({
      state: "finished",
      status: null,
      outcome: {
        outcome: "failed",
        error: { type: "LLMError", code: 5, message: "LLM answer was cut off at the output cap", reason: "llm_output_cap" },
        warnings: [],
      },
      cancelled: false,
    });
    const { unmount } = render(<Run run={RUN} pollMs={5} />);
    expect(await screen.findByText("LLM answer was cut off at the output cap")).toBeInTheDocument();
    unmount();
    sequence({ state: "finished", status: null, outcome: { outcome: "unreadable", exit_code: null }, cancelled: false });
    render(<Run run={RUN} pollMs={5} />);
    expect(await screen.findByText("The engine returned an unreadable result")).toBeInTheDocument();
  });

  it("offers recovery after a pending_recovery error, then the backup option if refused", async () => {
    sequence({
      state: "finished",
      status: null,
      outcome: {
        outcome: "failed",
        error: {
          type: "PendingRecoveryError",
          code: 4,
          message: "A previous workspace update needs recovery",
          reason: "pending_recovery",
        },
        warnings: [],
      },
      cancelled: false,
    });
    vi.mocked(api.run)
      .mockResolvedValueOnce({
        outcome: "failed",
        error: { type: "PendingRecoveryError", code: 4, message: "chapter 1 changed after the interruption" },
        warnings: [],
      })
      .mockResolvedValueOnce({ outcome: "success", result: { status: "recovered", backed_up: ["chapter 1"] } });
    render(<Run run={RUN} pollMs={5} />);
    expect(await screen.findByText("An earlier update was interrupted")).toBeInTheDocument();
    const recover = Array.from(document.querySelectorAll("md-filled-button")).find((button) =>
      button.textContent?.includes("Recover"),
    ) as HTMLElement;
    await act(async () => {
      recover.dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(api.run).toHaveBeenLastCalledWith(
      { command: "recover", manifest: RUN.manifest, back_up_changed: false },
      RUN.workspace,
    );
    expect(await screen.findByText("chapter 1 changed after the interruption")).toBeInTheDocument();
    await act(async () => {
      document.querySelector("md-outlined-button")?.dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(api.run).toHaveBeenLastCalledWith(
      { command: "recover", manifest: RUN.manifest, back_up_changed: true },
      RUN.workspace,
    );
    expect(await screen.findByText(/The interrupted update is complete. Backed up: chapter 1./)).toBeInTheDocument();
  });

  it("doesn't offer recovery for other failures", async () => {
    sequence({
      state: "finished",
      status: null,
      outcome: { outcome: "failed", error: { type: "AudioError", code: 6, message: "No audio" }, warnings: [] },
      cancelled: false,
    });
    render(<Run run={RUN} pollMs={5} />);
    expect(await screen.findByText("No audio")).toBeInTheDocument();
    expect(screen.queryByText("An earlier update was interrupted")).not.toBeInTheDocument();
  });

  it("opens review by itself, once, when a run stops for review", async () => {
    sequence({
      state: "finished",
      status: null,
      outcome: {
        outcome: "failed",
        error: {
          type: "AudioError",
          code: 6,
          message: "Chapter 1 has low boundary confidence; review the manifest before synthesis",
          reason: "review_required",
        },
        warnings: [],
      },
      cancelled: false,
    });
    const onReview = vi.fn();
    render(<Run run={RUN} pollMs={5} onReview={onReview} />);
    expect(await screen.findByText("This book's chapters need your review")).toBeInTheDocument();
    await waitFor(() => expect(onReview).toHaveBeenCalledOnce());
    act(() => {
      Array.from(document.querySelectorAll("md-filled-button"))
        .find((element) => element.textContent?.includes("Review chapters"))
        ?.dispatchEvent(new Event("click", { bubbles: true }));
    });
    expect(onReview).toHaveBeenCalledTimes(2);
  });

  it("opens review for a book-wide review reason too", async () => {
    sequence({
      state: "finished",
      status: null,
      outcome: {
        outcome: "failed",
        error: { type: "AudioError", code: 6, message: "damaged source", reason: "review_acknowledgement_required" },
        warnings: [],
      },
      cancelled: false,
    });
    const onReview = vi.fn();
    render(<Run run={RUN} pollMs={5} onReview={onReview} />);
    await screen.findByText("This book's chapters need your review");
    await waitFor(() => expect(onReview).toHaveBeenCalledOnce());
  });
});
