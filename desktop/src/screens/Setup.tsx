import { useEffect, useState } from "react";
import { describe, errorMessage, locateEngine, run } from "../engine/api";
import type { BridgeError, Doctor, EngineInfo, Request } from "../engine/types";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { CircularProgress } from "../ui/Progress";
import { Icon } from "../ui/Icon";
import { IconButton } from "../ui/IconButton";
import { setupChecks, type Check } from "./setupChecks";
import "./screens.css";

type State =
  | { phase: "loading" }
  | { phase: "no-engine"; error: BridgeError }
  | { phase: "failed"; message: string }
  | { phase: "ready"; engine: EngineInfo; doctor: Doctor };

const DOCTOR: Request = { command: "doctor" };
const DOCTOR_LLM: Request = { command: "doctor", check_llm: true };

interface Checked {
  state: State;
  commands: string[];
}

/** Finds the CLI and runs `doctor`; never rejects. */
export async function check(request: Request): Promise<Checked> {
  let engine: EngineInfo;
  try {
    engine = await locateEngine();
  } catch (error) {
    return { state: { phase: "no-engine", error: error as BridgeError }, commands: [] };
  }
  try {
    const outcome = await run<Doctor>(request);
    const shown = await describe(request).catch(() => null);
    const commands = [engine.command, ...(shown ? [shown] : [])];
    if (outcome.outcome === "success") {
      return { state: { phase: "ready", engine, doctor: outcome.result }, commands };
    }
    const message =
      outcome.outcome === "failed" ? outcome.error.message : "The engine returned an unreadable result";
    return { state: { phase: "failed", message }, commands };
  } catch (error) {
    return { state: { phase: "failed", message: errorMessage(error) }, commands: [] };
  }
}

/** Setup (spec D4.1): is everything pdf2audiobook needs installed? */
export function Setup() {
  const [result, setResult] = useState<Checked>({ state: { phase: "loading" }, commands: [] });
  const [request, setRequest] = useState<{ request: Request; attempt: number }>({
    request: DOCTOR,
    attempt: 0,
  });
  const [checkingLlm, setCheckingLlm] = useState(false);

  useEffect(() => {
    let current = true;
    void check(request.request).then((next) => {
      if (current) {
        setResult(next);
        setCheckingLlm(false);
      }
    });
    return () => {
      current = false;
    };
  }, [request]);

  const recheck = () => {
    setResult({ state: { phase: "loading" }, commands: [] });
    setRequest((previous) => ({ request: DOCTOR, attempt: previous.attempt + 1 }));
  };

  const checkLlm = () => {
    setCheckingLlm(true);
    setRequest((previous) => ({ request: DOCTOR_LLM, attempt: previous.attempt + 1 }));
  };

  const { state, commands } = result;

  return (
    <div className="screen setup">
      <div className="screen-intro">
        <p className="body-medium on-surface-variant">
          pdf2audiobook needs a few programs on this computer. Anything missing shows the exact
          command that installs it.
        </p>
        <IconButton icon="refresh" label="Check again" onClick={recheck} disabled={state.phase === "loading"} />
      </div>
      {state.phase === "loading" ? (
        <div className="screen-loading">
          <CircularProgress label="Checking your setup" />
          <span className="body-medium on-surface-variant">Checking your setup…</span>
        </div>
      ) : null}
      {state.phase === "no-engine" ? <NoEngine error={state.error} /> : null}
      {state.phase === "failed" ? (
        <Card variant="outlined" label="Setup check failed">
          <div className="notice notice-error">
            <Icon name="error" />
            <div>
              <div className="title-medium">The setup check failed</div>
              <p className="body-medium">{state.message}</p>
            </div>
          </div>
        </Card>
      ) : null}
      {state.phase === "ready" ? (
        <>
          <Summary checks={setupChecks(state.engine, state.doctor)} />
          <ul className="check-list" aria-label="Setup checks">
            {setupChecks(state.engine, state.doctor).map((check) => (
              <CheckRow
                key={check.id}
                check={check}
                action={
                  check.id === "llm" && state.doctor.llm_provider === "ollama" ? (
                    <Button variant="tonal" icon="sync" onClick={checkLlm} disabled={checkingLlm}>
                      {checkingLlm ? "Checking…" : "Check context"}
                    </Button>
                  ) : null
                }
              />
            ))}
          </ul>
        </>
      ) : null}
      {commands.length > 0 ? (
        <details className="details">
          <summary>Details</summary>
          <p className="body-medium on-surface-variant">Commands this screen ran:</p>
          {commands.map((command) => (
            <pre key={command} className="command">
              {command}
            </pre>
          ))}
        </details>
      ) : null}
    </div>
  );
}

function Summary({ checks }: { checks: Check[] }) {
  const attention = checks.filter((check) => check.state === "attention").length;
  return (
    <div className={`summary ${attention ? "summary-attention" : "summary-ok"}`} role="status">
      <Icon name={attention ? "warning" : "task_alt"} filled size={28} />
      <div>
        <div className="title-medium">
          {attention ? `${attention} ${attention === 1 ? "thing needs" : "things need"} attention` : "Everything is ready"}
        </div>
        <div className="body-medium">
          {attention ? "Fix these before converting a book." : "You can analyze and convert books."}
        </div>
      </div>
    </div>
  );
}

const STATE_ICON = { ok: "check_circle", attention: "warning", optional: "info" } as const;
const STATE_LABEL = { ok: "Ready", attention: "Needs attention", optional: "Optional" } as const;

function CheckRow({ check, action }: { check: Check; action: React.ReactNode }) {
  return (
    <li className={`check check-${check.state}`}>
      <span className="check-icon">
        <Icon name={check.icon} />
      </span>
      <div className="check-body">
        <div className="check-title">
          <span className="title-medium">{check.title}</span>
          <span className={`status-chip status-${check.state}`}>
            <Icon name={STATE_ICON[check.state]} filled size={16} />
            {STATE_LABEL[check.state]}
          </span>
        </div>
        <p className="body-medium on-surface-variant">{check.detail}</p>
        {check.fix ? <CopyCommand command={check.fix} /> : null}
      </div>
      {action ? <div className="check-action">{action}</div> : null}
    </li>
  );
}

function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="copy-command">
      <pre className="command">{command}</pre>
      <IconButton icon={copied ? "check" : "content_copy"} label={copied ? "Copied" : "Copy command"} onClick={copy} />
    </div>
  );
}

function NoEngine({ error }: { error: BridgeError }) {
  const mismatch = error.kind === "locate" && error.error.kind === "version_mismatch";
  return (
    <Card variant="outlined" label="pdf2audiobook was not found">
      <div className="notice notice-error">
        <Icon name="error" />
        <div>
          <div className="title-medium">
            {mismatch ? "This pdf2audiobook version can't be used" : "pdf2audiobook isn't installed"}
          </div>
          <p className="body-medium">{errorMessage(error)}</p>
          <p className="body-medium on-surface-variant">
            The app runs the pdf2audiobook command-line tool. Install it from a checkout of the
            project, then check again:
          </p>
          <CopyCommand command={'uv tool install ".[kitten]"'} />
          <p className="body-medium on-surface-variant">
            Or choose the CLI or a source checkout in Settings.
          </p>
        </div>
      </div>
    </Card>
  );
}
