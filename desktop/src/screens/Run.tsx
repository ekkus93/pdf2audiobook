import { useEffect, useState } from "react";
import { cancelRun, errorMessage, run as runEngine, runProgress } from "../engine/api";
import type { Progress, RunStatus } from "../engine/types";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { LinearProgress } from "../ui/Progress";
import "./screens.css";
import "./run.css";

export interface ActiveRun {
  id: number;
  title: string;
  command: "analyze" | "convert";
  workspace: string;
  manifest: string;
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

const UNITS: Record<string, string> = { char: "characters", request: "LLM requests", page: "pages", chapter: "chapters" };

interface RunProps {
  run: ActiveRun | null;
  onDone?: () => void;
  /** How often to poll `run_status.json` (spec D5.a: about once a second). */
  pollMs?: number;
}

/** Run (spec D4.4, D5): live progress for analyze or convert, with cancel. */
export function Run({ run, onDone, pollMs = 1000 }: RunProps) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

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

  const task = run.command === "convert" ? "Converting to audio" : "Analyzing";
  const status = progress?.status ?? null;
  return (
    <div className="screen run">
      <div className="run-header">
        <span className="run-art" aria-hidden="true">
          <Icon name={run.command === "convert" ? "graphic_eq" : "auto_stories"} size={32} />
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
      {progress?.state === "finished" ? <Finished progress={progress} task={task} onDone={onDone} /> : null}
      {progress?.state === "finished" &&
      progress.outcome.outcome === "failed" &&
      progress.outcome.error.reason === "pending_recovery" ? (
        <Recover manifest={run.manifest} workspace={run.workspace} />
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

function Finished({ progress, task, onDone }: { progress: Extract<Progress, { state: "finished" }>; task: string; onDone?: () => void }) {
  const { outcome, cancelled, status } = progress;
  const elapsed = status ? ` in ${duration(status.elapsed_seconds)}` : "";
  let icon: "task_alt" | "stop" | "error" = "task_alt";
  let heading = `${task === "Analyzing" ? "Analysis" : "Conversion"} finished${elapsed}`;
  let message: string | null = null;
  if (cancelled) {
    icon = "stop";
    heading = "Stopped";
    message = "The run stopped. Finished chapters are kept; run it again to continue.";
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
