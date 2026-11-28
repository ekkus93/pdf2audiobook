import { useEffect, useState } from "react";
import { run } from "../engine/api";
import type { LlmModels, LlmProvider } from "../engine/types";
import { IconButton } from "../ui/IconButton";
import { Select } from "../ui/Select";
import { TextField } from "../ui/TextField";

/** The Select value that switches to typing a model name. */
export const OTHER = "\u0000other";

type Served = { key: string } & ({ models: string[] } | { problem: string });

/** The listed model `value` names: Ollama treats "name" as "name:latest". */
export function listedAs(models: readonly string[], value: string): string | null {
  if (!value) return null;
  return models.find((model) => model === value || model === `${value}:latest`) ?? null;
}

/**
 * The LLM model: a list of what the server serves, asked each time the field appears or the
 * provider changes, plus "Another model…" for typing a name. OpenAI's list needs the book's
 * remote consent, and an unreachable server has no list, so those get the text field alone.
 * `provider` null means the CLI's configured provider. An empty `value` with `emptyLabel`
 * means "use the configured model" (Settings).
 */
export function ModelField({
  provider,
  value,
  onChange,
  errorText,
  emptyLabel,
}: {
  provider: LlmProvider | null;
  value: string;
  onChange: (value: string) => void;
  errorText?: string;
  emptyLabel?: string;
}) {
  const [answer, setAnswer] = useState<Served | null>(null);
  const [typing, setTyping] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const listable = provider !== "openai";
  // The answer belongs to one provider and one refresh; an older one is not shown.
  const key = `${provider ?? ""}|${refresh}`;
  const served = answer?.key === key ? answer : null;
  useEffect(() => {
    if (!listable) return;
    let current = true;
    run<LlmModels>({ command: "llm_models", llm_provider: provider })
      .then((result) => {
        if (!current) return;
        if (result.outcome === "success") setAnswer({ key, models: result.result.models });
        else setAnswer({ key, problem: result.outcome === "failed" ? result.error.message : "The model list is unavailable" });
      })
      .catch(() => current && setAnswer({ key, problem: "The model list is unavailable" }));
    return () => {
      current = false;
    };
  }, [provider, listable, key]);
  const models = listable && served && "models" in served ? served.models : null;
  const shown = models ? (value === "" ? (emptyLabel ? "" : null) : listedAs(models, value)) : null;
  if (!models || models.length === 0 || typing || shown === null) {
    const note = !listable
      ? undefined
      : served && "problem" in served
        ? `${served.problem}; type the model's name`
        : models && models.length === 0
          ? "The server lists no models; type the model's name"
          : models && value && !listedAs(models, value)
            ? "Not one the server lists"
            : undefined;
    return (
      <div className="model-field">
        <TextField label="Model" value={value} onChange={onChange} errorText={errorText} supportingText={note ?? (emptyLabel && !value ? emptyLabel : undefined)} />
        {models && models.length > 0 ? (
          <IconButton
            icon="expand_more"
            label="Choose from the server's models"
            onClick={() => {
              setTyping(false);
              if (!listedAs(models, value)) onChange(emptyLabel ? "" : models[0]);
            }}
          />
        ) : listable ? (
          <IconButton icon="refresh" label="Ask the server for its models again" onClick={() => setRefresh((count) => count + 1)} />
        ) : null}
      </div>
    );
  }
  const options = [
    ...(emptyLabel ? [{ value: "", label: emptyLabel }] : []),
    ...models.map((model) => ({ value: model, label: model })),
    { value: OTHER, label: "Another model…" },
  ];
  return (
    <div className="model-field">
      <Select
        label="Model"
        value={shown}
        options={options}
        onChange={(choice) => {
          if (choice === OTHER) setTyping(true);
          else onChange(choice);
        }}
      />
      <IconButton icon="refresh" label="Ask the server for its models again" onClick={() => setRefresh((count) => count + 1)} />
    </div>
  );
}
