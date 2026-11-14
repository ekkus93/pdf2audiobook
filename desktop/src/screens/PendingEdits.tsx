import { useEffect, useState } from "react";
import { errorMessage, run } from "../engine/api";
import type { PendingEdit, Request } from "../engine/types";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { CircularProgress } from "../ui/Progress";
import "./edits.css";

interface PendingEditsProps {
  manifest: string;
  workspace: string;
  /** Called after any accept or reject, so the book can be re-read. */
  onChanged?: () => void;
}

type State =
  | { phase: "loading" }
  | { phase: "failed"; message: string }
  | { phase: "ready"; edits: PendingEdit[] };

/** Loads the book's pending edits with their text; never rejects. */
export async function loadEdits(manifest: string): Promise<State> {
  try {
    const outcome = await run<{ edits: PendingEdit[] }>({ command: "edits_list", manifest, status: "pending", with_text: true });
    if (outcome.outcome === "success") {
      return { phase: "ready", edits: Array.isArray(outcome.result.edits) ? outcome.result.edits : [] };
    }
    return {
      phase: "failed",
      message: outcome.outcome === "failed" ? outcome.error.message : "The engine returned an unreadable result",
    };
  } catch (error) {
    return { phase: "failed", message: errorMessage(error) };
  }
}

/** Pending edits (spec D4.6): what the LLM proposed, accepted or rejected one by one or all at once. */
export function PendingEdits({ manifest, workspace, onChanged }: PendingEditsProps) {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);

  useEffect(() => {
    let current = true;
    void loadEdits(manifest).then((next) => current && setState(next));
    return () => {
      current = false;
    };
  }, [manifest, attempt]);

  const decide = async (request: Request) => {
    setBusy(true);
    setProblem(null);
    try {
      const outcome = await run(request, workspace);
      if (outcome.outcome === "failed") setProblem(outcome.error.message);
      else if (outcome.outcome === "unreadable") setProblem("The engine returned an unreadable result");
    } catch (error) {
      setProblem(errorMessage(error));
    }
    setBusy(false);
    setAttempt((value) => value + 1);
    onChanged?.();
  };

  const one = (verb: "edits_accept" | "edits_reject", id: string) =>
    void decide({ command: verb, manifest, which: { kind: "blocks", ids: [id] } });

  if (state.phase === "loading") {
    return (
      <section className="edits" aria-label="Pending edits">
        <CircularProgress label="Loading pending edits" />
      </section>
    );
  }
  if (state.phase === "failed") {
    return (
      <section className="edits" aria-label="Pending edits">
        <h3 className="title-medium">Pending edits</h3>
        <p className="body-medium edits-problem">{state.message}</p>
      </section>
    );
  }
  const count = state.edits.length;
  return (
    <section className="edits" aria-labelledby="edits-heading">
      <div className="edits-top">
        <div>
          <h3 id="edits-heading" className="title-medium">
            Pending edits {count ? <span className="edits-count">{count}</span> : null}
          </h3>
          <p className="body-medium on-surface-variant">
            {count
              ? "The LLM proposed these changes. None reaches the audio until you accept it."
              : "No edits are waiting for you."}
          </p>
        </div>
        {count > 1 ? (
          <Button variant="tonal" icon="done_all" onClick={() => setConfirmAll(true)} disabled={busy}>
            Accept all
          </Button>
        ) : null}
      </div>
      {problem ? <p className="body-medium edits-problem">{problem}</p> : null}
      {count ? (
        <ul className="edit-list" aria-label="Edits">
          {state.edits.map((edit) => (
            <li key={edit.block_id} className="edit" aria-label={`Edit ${edit.block_id}`}>
              <div className="edit-meta label-large on-surface-variant">
                {edit.chapter !== null ? `Chapter ${edit.chapter}` : "No chapter"} · {edit.provider}
              </div>
              <div className="edit-change">
                <del className="edit-was">{edit.original ?? ""}</del>
                <ins className="edit-now">{edit.replacement ?? ""}</ins>
              </div>
              {edit.reason ? <p className="body-medium on-surface-variant edit-why">{edit.reason}</p> : null}
              <div className="button-row">
                <Button variant="tonal" icon="check" onClick={() => one("edits_accept", edit.block_id)} disabled={busy}>
                  Accept
                </Button>
                <Button variant="text" icon="close" onClick={() => one("edits_reject", edit.block_id)} disabled={busy}>
                  Reject
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      <Dialog
        open={confirmAll}
        headline={`Accept all ${count} edits?`}
        onClose={() => setConfirmAll(false)}
        actions={
          <>
            <Button variant="text" onClick={() => setConfirmAll(false)}>
              Cancel
            </Button>
            <Button
              icon="done_all"
              onClick={() => {
                setConfirmAll(false);
                void decide({ command: "edits_accept", manifest, which: { kind: "all" } });
              }}
            >
              Accept {count}
            </Button>
          </>
        }
      >
        All {count} proposed changes go into the chapter text and the audio. Accepting counts as
        approving the book, so it won't be re-analyzed over your decisions.
      </Dialog>
    </section>
  );
}
