import { useEffect, useState } from "react";
import { errorMessage, run as runEngine } from "../engine/api";
import type { BudgetReport, CliConfig, InspectManifest, Request } from "../engine/types";
import { Button } from "../ui/Button";

/** The D2.b reasons this module handles; review and recovery have their own sections in Run. */
export const ACTION_REASONS = [
  "review_acknowledgement_required",
  "workspace_locked",
  "chapter_conflict",
  "llm_unreachable",
  "llm_context_too_small",
  "llm_output_cap",
  "budget_exhausted",
] as const;
export type ActionReason = (typeof ACTION_REASONS)[number];

export function isActionReason(reason: string | null | undefined): reason is ActionReason {
  return (ACTION_REASONS as readonly string[]).includes(reason ?? "");
}

export interface ReasonContext {
  /** The request that stopped, to run again (with changes) from here. */
  request: Request;
  manifest: string;
  workspace: string;
  /** The engine's own message, shown as it is. */
  message: string;
  /** Starts `request` again; `waitForLock` keeps retrying while another task holds the book. */
  onRestart: (request: Request, options?: { waitForLock?: boolean }) => void;
  onOpenSettings?: () => void;
  onOpenBook?: () => void;
  /** True when this run was started to wait for the book's lock. */
  waitingForLock?: boolean;
  /** Seconds between retries while waiting for the lock. */
  lockRetrySeconds?: number;
}

/** The section a reason leads to (spec D2.b's "App action" column). */
export function ReasonAction({ reason, context }: { reason: ActionReason; context: ReasonContext }) {
  switch (reason) {
    case "review_acknowledgement_required":
      return <Acknowledge context={context} />;
    case "workspace_locked":
      return <Locked context={context} />;
    case "chapter_conflict":
      return <Conflict context={context} />;
    case "llm_unreachable":
      return (
        <Panel label="LLM unreachable" title="The LLM server couldn't be reached">
          <p className="body-medium on-surface-variant">
            Check that the server is running and that the provider and model in Settings match it.
            The setup check there can test the connection.
          </p>
          <div className="button-row">
            <Button icon="settings" onClick={() => context.onOpenSettings?.()} disabled={!context.onOpenSettings}>
              Open LLM settings
            </Button>
          </div>
        </Panel>
      );
    case "llm_context_too_small":
      return (
        <Panel label="LLM context too small" title="The model's context is too small for this run">
          <p className="body-medium on-surface-variant">
            The server answers with a smaller context than the run needs. With Ollama a plain model
            tag often has a small default; create a variant with a larger <code>num_ctx</code>, for
            example <code>printf 'FROM qwen3.5:9b\nPARAMETER num_ctx 262144\n' &gt; Modelfile</code> then{" "}
            <code>ollama create qwen35-256k -f Modelfile</code>, and choose that model with a matching{" "}
            <strong>Context (tokens)</strong> in the book's options. The served context must be
            larger than the output cap plus a window of text.
          </p>
          <div className="button-row">
            <Button icon="tune" onClick={() => context.onOpenBook?.()} disabled={!context.onOpenBook}>
              Change the context
            </Button>
          </div>
        </Panel>
      );
    case "llm_output_cap":
      return (
        <Panel label="LLM output cap" title="An answer was cut off at the output cap">
          <p className="body-medium on-surface-variant">
            Raise <strong>Output cap (tokens)</strong> in the book's options. Thinking models spend
            output on reasoning before they answer; 32768 is a good start for them.
          </p>
          <div className="button-row">
            <Button icon="tune" onClick={() => context.onOpenBook?.()} disabled={!context.onOpenBook}>
              Change the output cap
            </Button>
          </div>
        </Panel>
      );
    case "budget_exhausted":
      return <Budget context={context} />;
  }
}

function Panel({ label, title, children }: { label: string; title: string; children: React.ReactNode }) {
  return (
    <section className="recover" aria-label={label}>
      <div className="title-medium">{title}</div>
      {children}
    </section>
  );
}

const BOOK_WIDE: Record<string, string> = {
  damaged_source: "Some pages couldn't be read cleanly, so the audio may skip or garble text there.",
  ambiguous_page_numbers: "Page numbers were removed where it wasn't certain they were page numbers.",
};

/** The book-wide reasons the book still needs acknowledged. */
export function unacknowledged(inspect: InspectManifest): string[] {
  return inspect.review_required.filter((reason) => reason in BOOK_WIDE && !inspect.review_acknowledged.includes(reason));
}

function Acknowledge({ context }: { context: ReasonContext }) {
  const [reasons, setReasons] = useState<string[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    void runEngine<InspectManifest>({ command: "inspect", source: context.manifest })
      .then((outcome) => {
        if (!current) return;
        if (outcome.outcome === "success") setReasons(unacknowledged(outcome.result));
        else setProblem(outcome.outcome === "failed" ? outcome.error.message : "The engine returned an unreadable result");
      })
      .catch((error: unknown) => current && setProblem(errorMessage(error)));
    return () => {
      current = false;
    };
  }, [context.manifest]);

  const request = context.request;
  const canRestart = request.command === "convert" && reasons !== null && reasons.length > 0;
  return (
    <Panel label="Acknowledge" title="This book needs your acknowledgement before converting">
      <p className="body-medium on-surface-variant">
        You can check the affected chapters in review, or convert anyway once you've read why.
      </p>
      {problem ? <p className="body-medium">{problem}</p> : null}
      {reasons ? (
        <ul className="reason-list">
          {reasons.map((reason) => (
            <li key={reason} className="body-medium">
              <code>{reason}</code>: {BOOK_WIDE[reason]}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="button-row">
        <Button
          icon="done_all"
          disabled={!canRestart}
          onClick={() => {
            if (request.command !== "convert" || !reasons) return;
            const accepted = [...new Set([...(request.convert.accept_review ?? []), ...reasons])] as Array<
              "damaged_source" | "ambiguous_page_numbers"
            >;
            context.onRestart({ ...request, convert: { ...request.convert, accept_review: accepted } });
          }}
        >
          Acknowledge and convert
        </Button>
      </div>
    </Panel>
  );
}

function Locked({ context }: { context: ReasonContext }) {
  const [waiting, setWaiting] = useState(Boolean(context.waitingForLock));
  const seconds = context.lockRetrySeconds ?? 5;

  useEffect(() => {
    if (!waiting) return undefined;
    const timer = setTimeout(() => context.onRestart(context.request, { waitForLock: true }), seconds * 1000);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one retry per wait
  }, [waiting]);

  return (
    <Panel label="Book in use" title="Another task is using this book">
      <p className="body-medium on-surface-variant">
        {waiting
          ? `Waiting for it to finish; trying again every ${seconds} seconds.`
          : "Wait for it to finish and this task starts by itself, or cancel."}
      </p>
      <div className="button-row">
        {waiting ? (
          <Button variant="outlined" icon="close" onClick={() => setWaiting(false)}>
            Cancel
          </Button>
        ) : (
          <>
            <Button icon="hourglass_top" onClick={() => setWaiting(true)}>
              Wait and try again
            </Button>
            <Button variant="text" icon="close" onClick={() => context.onOpenBook?.()} disabled={!context.onOpenBook}>
              Cancel
            </Button>
          </>
        )}
      </div>
    </Panel>
  );
}

function Conflict({ context }: { context: ReasonContext }) {
  const chapter = Number(/Chapter (\d+)/.exec(context.message)?.[1] ?? NaN);
  const [state, setState] = useState<{ phase: "idle" | "working" | "done" | "failed"; message?: string }>({ phase: "idle" });
  const regenerate = async () => {
    setState({ phase: "working" });
    try {
      const outcome = await runEngine<{ regenerated: number[]; backed_up: string[] }>(
        {
          command: "regenerate_chapter",
          manifest: context.manifest,
          which: Number.isInteger(chapter) ? { kind: "chapter", chapter } : { kind: "all_conflicts" },
        },
        context.workspace,
      );
      if (outcome.outcome === "success") {
        const backups = outcome.result.backed_up;
        setState({
          phase: "done",
          message: `Regenerated.${backups.length ? ` Your edited file was kept as ${backups.map((path) => path.split(/[\\/]/).pop()).join(", ")}.` : ""}`,
        });
      } else {
        setState({ phase: "failed", message: outcome.outcome === "failed" ? outcome.error.message : "The engine returned an unreadable result" });
      }
    } catch (error) {
      setState({ phase: "failed", message: errorMessage(error) });
    }
  };
  const which = Number.isInteger(chapter) ? `chapter ${chapter}` : "the conflicting chapters";
  return (
    <Panel label="Chapter conflict" title={`The text file for ${which} was edited`}>
      <p className="body-medium on-surface-variant">
        It no longer matches what the book generates. Regenerating replaces it and keeps your
        edited file as a backup next to it.
      </p>
      {state.message ? <p className="body-medium">{state.message}</p> : null}
      <div className="button-row">
        {state.phase === "done" ? (
          <Button icon="replay" onClick={() => context.onRestart(context.request)}>
            Run again
          </Button>
        ) : (
          <Button icon="sync" onClick={() => void regenerate()} disabled={state.phase === "working"}>
            {state.phase === "working" ? "Regenerating…" : `Regenerate ${which} with a backup`}
          </Button>
        )}
      </div>
    </Panel>
  );
}

function number(value: number): string {
  return value.toLocaleString("en-US");
}

/** The budget screen: what the book's LLM requests used, against the configured limits. */
function Budget({ context }: { context: ReasonContext }) {
  const [report, setReport] = useState<BudgetReport | null>(null);
  const [limits, setLimits] = useState<CliConfig["llm"] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    void (async () => {
      try {
        const [budget, config] = await Promise.all([
          runEngine<BudgetReport>({ command: "budget_show", workspace: context.workspace }),
          runEngine<CliConfig>({ command: "config_show" }),
        ]);
        if (!current) return;
        if (budget.outcome === "success") setReport(budget.result);
        else setProblem(budget.outcome === "failed" ? budget.error.message : "The engine returned an unreadable result");
        if (config.outcome === "success") setLimits(config.result.llm);
      } catch (error) {
        if (current) setProblem(errorMessage(error));
      }
    })();
    return () => {
      current = false;
    };
  }, [context.workspace]);

  const limit = (value: number | null | undefined, format: (value: number) => string) =>
    value === null || value === undefined ? "no limit" : format(value);
  return (
    <Panel label="LLM budget" title="This book's LLM budget is used up">
      <p className="body-medium on-surface-variant">
        To continue, raise the limit in <code>~/.config/pdf2audiobook/config.toml</code> (<code>[llm]</code>{" "}
        <code>max_requests</code>, <code>max_reported_tokens</code> or <code>max_estimated_cost_usd</code>) or
        the matching <code>PDF2AUDIOBOOK_LLM_…</code> environment variable, then run again.
      </p>
      {problem ? <p className="body-medium">{problem}</p> : null}
      {report ? (
        <table className="config-table budget-table" aria-label="LLM budget">
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col">Used</th>
              <th scope="col">Limit</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Requests</td>
              <td>{number(report.totals.requests_started)}</td>
              <td>{limit(limits?.max_requests, number)}</td>
            </tr>
            <tr>
              <td>Reported tokens</td>
              <td>{number(report.totals.reported_tokens)}</td>
              <td>{limit(limits?.max_reported_tokens, number)}</td>
            </tr>
            <tr>
              <td>Estimated cost</td>
              <td>${report.totals.estimated_cost_usd.toFixed(4)}</td>
              <td>{limit(limits?.max_estimated_cost_usd, (value) => `$${value.toFixed(4)}`)}</td>
            </tr>
          </tbody>
        </table>
      ) : null}
      {report && report.totals.unresolved_requests > 0 ? (
        <p className="body-medium on-surface-variant">
          {report.totals.unresolved_requests} request(s) never reported their usage. After checking your
          provider's billing, settle each one with <code>pdf2audiobook budget resolve</code> (see{" "}
          <code>budget resolve --help</code>).
        </p>
      ) : null}
      <div className="button-row">
        <Button icon="replay" onClick={() => context.onRestart(context.request)}>
          Run again
        </Button>
      </div>
    </Panel>
  );
}
