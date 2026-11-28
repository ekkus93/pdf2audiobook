import { useEffect, useState } from "react";
import { cancelRun, errorMessage, run as runEngine, runProgress } from "../engine/api";
import type { Progress, Request, RunStatus } from "../engine/types";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { LinearProgress } from "../ui/Progress";
import { CutOffNotices, ReasonAction, isActionReason, type ReasonContext } from "./reasons";
import "./screens.css";
import "./run.css";

export interface ActiveRun {
  id: number;
  title: string;
  command: "analyze" | "convert" | "verify_audio" | "resynthesize" | "tts_fetch";
  workspace: string;
  manifest: string;
  /** The request that started the run, to start again from the reason actions. */
  request?: Request;
  /** True when this run was started to wait for another task to release the book. */
  waitingForLock?: boolean;
}

/** "45s", "4m 12s", "1h 03m". */
export function duration(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  return `${rest}s`;
}

const TASKS: Record<ActiveRun["command"], string> = {
  tts_fetch: "Downloading KittenTTS 2",
  analyze: "Analyzing",
  convert: "Converting to audio",
  verify_audio: "Checking the audio",
  resynthesize: "Speaking chapters again",
};

const DONE: Record<ActiveRun["command"], string> = {
  tts_fetch: "Model download finished",
  analyze: "Analysis finished",
  convert: "Conversion finished",
  verify_audio: "Audio check finished",
  resynthesize: "Chapters spoken again",
};

const ICONS: Record<ActiveRun["command"], "auto_stories" | "graphic_eq" | "hearing"> = {
  tts_fetch: "graphic_eq",
  analyze: "auto_stories",
  convert: "graphic_eq",
  verify_audio: "hearing",
  resynthesize: "graphic_eq",
};

const STOPPED: Record<ActiveRun["command"], string> = {
  tts_fetch: "The download stopped. Verified files are kept; set up the model again to continue.",
  analyze: "The run stopped. Finished chapters are kept; run it again to continue.",
  convert: "The run stopped. Finished chapters are kept; run it again to continue.",
  verify_audio: "The check stopped. Chapters already checked are kept in the report; no audio was changed.",
  resynthesize: "The run stopped. Each chapter keeps its previous audio until its new audio is ready.",
};

const UNITS: Record<string, string> = { char: "characters", request: "LLM requests", page: "pages", chapter: "chapters" };

interface RunProps {
  run: ActiveRun | null;
  onDone?: () => void;
  /** Opens chapter review for the run's book (spec D4.5). */
  onReview?: () => void;
  /** How often to poll `run_status.json` (spec D5.a: about once a second). */
  pollMs?: number;
  /** Starts a request again (spec D2.b actions). */
  onRestart?: ReasonContext["onRestart"];
  onOpenSettings?: () => void;
  /** Seconds between retries while waiting for the book's lock. */
  lockRetrySeconds?: number;
}

/** Run (spec D4.4, D5): live progress for analyze or convert, with cancel. */
const REVIEW_REASONS = new Set(["review_required", "review_acknowledgement_required"]);

/** The engine's notices about LLM answers cut off at the output cap, from a finished analysis. */
function cutOffNotices(progress: Progress | null): string[] {
  if (progress?.state !== "finished" || progress.cancelled || progress.outcome.outcome !== "success") return [];
  const notices = progress.outcome.result.notices;
  return Array.isArray(notices) ? notices.filter((notice): notice is string => typeof notice === "string") : [];
}

/** The review reason a finished run stopped with, if any. */
function reviewReason(progress: Progress | null): string | null {
  if (progress?.state !== "finished" || progress.outcome.outcome !== "failed") return null;
  const reason = progress.outcome.error.reason ?? null;
  return reason && REVIEW_REASONS.has(reason) ? reason : null;
}

export function Run({ run, onDone, onReview, pollMs = 1000, onRestart, onOpenSettings, lockRetrySeconds }: RunProps) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const needsReview = reviewReason(progress) !== null;
  const notices = cutOffNotices(progress);

  // A run that stops for review opens the review page once, by itself (spec D4.5).
  useEffect(() => {
    if (needsReview) onReview?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per run that needs review
  }, [needsReview]);

  useEffect(() => {
    if (!run) return undefined;
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await runProgress(run.id);
        if (!current) return;
        setProgress(next);
        if (next.state === "running") timer = setTimeout(poll, pollMs);
      } catch (error) {
        if (current) setProblem(errorMessage(error));
      }
    };
    void poll();
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [run, pollMs]);

  if (!run) {
    return (
      <div className="empty-state">
        <span className="empty-art" aria-hidden="true">
          <Icon name="graphic_eq" size={56} />
        </span>
        <h2 className="headline-small">Nothing is running</h2>
        <p className="body-medium">Open a book and choose Analyze or Convert to see its progress here.</p>
      </div>
    );
  }

  const task = TASKS[run.command];
  const status = run.command === "tts_fetch" ? null : progress?.status ?? null;
  return (
    <div className="screen run">
      <div className="run-header">
        <span className="run-art" aria-hidden="true">
          <Icon name={ICONS[run.command]} size={32} />
        </span>
        <div>
          <h2 className="headline-small run-title">{run.title}</h2>
          <p className="body-medium on-surface-variant">{task}</p>
        </div>
      </div>
      {problem ? <p className="body-medium run-problem">{problem}</p> : null}
      {progress === null ? <LinearProgress label="Starting" /> : null}
      {progress?.state === "running" ? (
        <Running status={status} cancelling={progress.cancelling} onCancel={() => void cancelRun(run.id)} />
      ) : null}
      {progress?.state === "finished" ? <Finished progress={progress} command={run.command} onDone={onDone} /> : null}
      {notices.length ? <CutOffNotices notices={notices} onOpenBook={onDone} /> : null}
      {needsReview && onReview ? (
        <section className="recover" aria-label="Review">
          <div className="title-medium">This book's chapters need your review</div>
          <p className="body-medium on-surface-variant">
            The review page has opened in its own window. Check the chapters there, save, close it,
            then run the task again.
          </p>
          <div className="button-row">
            <Button icon="rate_review" onClick={onReview}>
              Review chapters
            </Button>
          </div>
        </section>
      ) : null}
      {progress?.state === "finished" &&
      progress.outcome.outcome === "failed" &&
      progress.outcome.error.reason === "pending_recovery" ? (
        <Recover manifest={run.manifest} workspace={run.workspace} />
      ) : null}
      {progress?.state === "finished" &&
      progress.outcome.outcome === "failed" &&
      isActionReason(progress.outcome.error.reason) &&
      run.request &&
      onRestart ? (
        <ReasonAction
          reason={progress.outcome.error.reason}
          context={{
            request: run.request,
            manifest: run.manifest,
            workspace: run.workspace,
            message: progress.outcome.error.message,
            onRestart,
            onOpenSettings,
            onOpenBook: onDone,
            waitingForLock: run.waitingForLock,
            lockRetrySeconds,
          }}
        />
      ) : null}
      {status?.completed_stages?.length ? (
        <section className="stages" aria-label="Finished stages">
          {status.completed_stages.map((stage) => (
            <div key={`${stage.name}-${stage.seconds}`} className="stage-done">
              <Icon name="check_circle" filled size={20} />
              <span>{stage.name}</span>
              <span className="on-surface-variant">{duration(stage.seconds)}</span>
            </div>
          ))}
        </section>
      ) : null}
    </div>
  );
}

function Running({ status, cancelling, onCancel }: { status: RunStatus | null; cancelling: boolean; onCancel: () => void }) {
  const stage = status?.stage ?? null;
  const fraction = stage?.total ? Math.min(1, stage.done / stage.total) : undefined;
  return (
    <section className="run-stage" aria-label="Current stage">
      <div className="run-stage-top">
        <div>
          <div className="title-medium">{stage?.name ?? "Starting…"}</div>
          {stage?.detail ? <div className="body-medium on-surface-variant">{stage.detail}</div> : null}
        </div>
        {fraction !== undefined ? <div className="run-percent">{Math.floor(fraction * 100)}%</div> : null}
      </div>
      <LinearProgress value={fraction} label={stage?.name ?? "Starting"} />
      <div className="run-facts body-medium on-surface-variant">
        {stage?.total ? (
          <span>
            {stage.done.toLocaleString("en-US")} of {stage.total.toLocaleString("en-US")} {UNITS[stage.unit] ?? stage.unit}
          </span>
        ) : null}
        {status ? <span>{duration(status.elapsed_seconds)} elapsed</span> : null}
        {stage?.estimated_remaining_seconds != null ? (
          <span>about {duration(stage.estimated_remaining_seconds)} left</span>
        ) : stage ? (
          <span>estimating…</span>
        ) : null}
      </div>
      <div className="button-row">
        <Button variant="outlined" icon="stop" onClick={onCancel} disabled={cancelling}>
          {cancelling ? "Stopping…" : "Stop"}
        </Button>
      </div>
    </section>
  );
}

function Finished({ progress, command, onDone }: { progress: Extract<Progress, { state: "finished" }>; command: ActiveRun["command"]; onDone?: () => void }) {
  const { outcome, cancelled, status } = progress;
  const elapsed = status ? ` in ${duration(status.elapsed_seconds)}` : "";
  let icon: "task_alt" | "stop" | "error" = "task_alt";
  let heading = `${DONE[command]}${elapsed}`;
  let message: string | null = null;
  if (cancelled) {
    icon = "stop";
    heading = "Stopped";
    message = STOPPED[command];
  } else if (outcome.outcome === "failed") {
    icon = "error";
    heading = "The run stopped with a problem";
    message = outcome.error.message;
  } else if (outcome.outcome === "unreadable") {
    icon = "error";
    heading = "The run ended unexpectedly";
    message = "The engine returned an unreadable result";
  }
  return (
    <section className={`run-result run-result-${icon}`} role="status">
      <Icon name={icon} filled size={28} />
      <div>
        <div className="title-medium">{heading}</div>
        {message ? <p className="body-medium">{message}</p> : null}
        {onDone ? (
          <div className="button-row">
            <Button variant="tonal" icon="arrow_back" onClick={onDone}>
              Back to the book
            </Button>
          </div>
        ) : null}
      </div>
    </section>
  );
}

type RecoverState =
  | { phase: "idle" }
  | { phase: "working" }
  | { phase: "done"; message: string }
  | { phase: "blocked"; message: string };

/** After a `pending_recovery` error: finish the interrupted update with `recover` (spec D5.c). */
function Recover({ manifest, workspace }: { manifest: string; workspace: string }) {
  const [state, setState] = useState<RecoverState>({ phase: "idle" });
  const recover = async (backUpChanged: boolean) => {
    setState({ phase: "working" });
    try {
      const outcome = await runEngine<{ status: string; backed_up: string[] }>(
        { command: "recover", manifest, back_up_changed: backUpChanged },
        workspace,
      );
      if (outcome.outcome === "success") {
        const backups = outcome.result.backed_up;
        const message =
          outcome.result.status === "nothing_pending"
            ? "Nothing was left to recover."
            : `The interrupted update is complete.${backups.length ? ` Backed up: ${backups.join(", ")}.` : ""} Run the task again.`;
        setState({ phase: "done", message });
      } else if (outcome.outcome === "failed") {
        setState({ phase: "blocked", message: outcome.error.message });
      } else {
        setState({ phase: "blocked", message: "The engine returned an unreadable result" });
      }
    } catch (error) {
      setState({ phase: "blocked", message: errorMessage(error) });
    }
  };
  return (
    <section className="recover" aria-label="Recovery">
      <div className="title-medium">An earlier update was interrupted</div>
      <p className="body-medium on-surface-variant">
        A previous review or regeneration stopped part-way. Recovery finishes it, then you can run
        this task again.
      </p>
      {state.phase === "done" || state.phase === "blocked" ? <p className="body-medium">{state.message}</p> : null}
      <div className="button-row">
        {state.phase !== "done" ? (
          <Button icon="replay" onClick={() => void recover(false)} disabled={state.phase === "working"}>
            {state.phase === "working" ? "Recovering…" : "Recover"}
          </Button>
        ) : null}
        {state.phase === "blocked" ? (
          <Button variant="outlined" icon="content_copy" onClick={() => void recover(true)}>
            Back up the changed files and recover
          </Button>
        ) : null}
      </div>
    </section>
  );
}
