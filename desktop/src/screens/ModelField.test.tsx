import { act, render } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LlmProvider, Request } from "../engine/types";

vi.mock("../engine/api", async (original) => ({
  ...(await original<typeof import("../engine/api")>()),
  run: vi.fn(),
}));

import * as api from "../engine/api";
import { listedAs, ModelField, OTHER } from "./ModelField";

const SERVED = ["qwen3.5:9b", "qwen35-256k:latest", "devstral-small-2:24b"];

function serve(models: string[] | null) {
  vi.mocked(api.run).mockImplementation(async (request: Request) => {
    expect(request.command).toBe("llm_models");
    if (models === null) {
      return { outcome: "failed", error: { kind: "engine", message: "Could not discover the served LLM models", reason: "llm_unreachable" } } as never;
    }
    return { outcome: "success", result: { provider: "ollama", configured: "qwen3.5:9b", models } } as never;
  });
}

const changes: string[] = [];

function Field({ provider = "ollama", initial, emptyLabel }: { provider?: LlmProvider | null; initial: string; emptyLabel?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <ModelField
      provider={provider}
      value={value}
      emptyLabel={emptyLabel}
      onChange={(next) => {
        changes.push(next);
        setValue(next);
      }}
    />
  );
}

async function show(element: React.ReactElement) {
  render(element);
  await act(async () => undefined);
}

type Labelled = HTMLElement & { label: string; supportingText?: string };
const byLabel = (tag: string) =>
  (Array.from(document.querySelectorAll(tag)) as Labelled[]).find((element) => element.label === "Model") ?? null;
const select = () => byLabel("md-outlined-select");
const text = () => byLabel("md-outlined-text-field");
type Option = HTMLElement & { value: string; selected: boolean };
const all = () => Array.from(document.querySelectorAll("md-select-option")) as Option[];
const options = () => all().map((option) => option.value);
const selected = () => all().find((option) => option.selected)?.value;

async function choose(value: string) {
  const element = select();
  if (!element) throw new Error("no model list");
  const spy = vi.spyOn(Object.getPrototypeOf(element), "value", "get").mockReturnValue(value);
  await act(async () => {
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
  spy.mockRestore();
}

async function press(label: string) {
  const button = document.querySelector(`[aria-label="${label}"]`) as HTMLElement;
  await act(async () => {
    button.dispatchEvent(new Event("click", { bubbles: true }));
  });
}

beforeEach(() => {
  changes.length = 0;
  vi.mocked(api.run).mockReset();
});

describe("ModelField", () => {
  it("offers the models the server serves, the chosen one selected", async () => {
    serve(SERVED);
    await show(<Field initial="qwen3.5:9b" />);
    expect(api.run).toHaveBeenCalledWith({ command: "llm_models", llm_provider: "ollama" });
    expect(options()).toEqual([...SERVED, OTHER]);
    expect(selected()).toBe("qwen3.5:9b");
    await choose("devstral-small-2:24b");
    expect(changes).toEqual(["devstral-small-2:24b"]);
  });

  it("treats a name without a tag as Ollama's :latest", async () => {
    expect(listedAs(SERVED, "qwen35-256k")).toBe("qwen35-256k:latest");
    expect(listedAs(SERVED, "qwen35")).toBeNull();
    serve(SERVED);
    await show(<Field initial="qwen35-256k" />);
    expect(selected()).toBe("qwen35-256k:latest");
    expect(changes).toEqual([]);
  });

  it("switches to typing a name, and back to the list", async () => {
    serve(SERVED);
    await show(<Field initial="qwen3.5:9b" />);
    await choose(OTHER);
    expect(select()).toBeNull();
    expect(text()).not.toBeNull();
    expect(changes).toEqual([]);
    await press("Choose from the server's models");
    expect(select()).not.toBeNull();
  });

  it("keeps a model the server does not list as text, and says so", async () => {
    serve(SERVED);
    await show(<Field initial="llama3:70b" />);
    expect(select()).toBeNull();
    expect(text()?.supportingText).toBe("Not one the server lists");
  });

  it("falls back to typing when the server cannot be reached, and can ask again", async () => {
    serve(null);
    await show(<Field initial="qwen3.5:9b" />);
    expect(select()).toBeNull();
    expect(text()?.supportingText).toBe("Could not discover the served LLM models; type the model's name");
    serve(SERVED);
    await press("Ask the server for its models again");
    expect(api.run).toHaveBeenCalledTimes(2);
    expect(select()).not.toBeNull();
  });

  it("does not ask OpenAI, whose list needs the book's remote consent", async () => {
    await show(<Field provider="openai" initial="gpt-5" />);
    expect(api.run).not.toHaveBeenCalled();
    expect(text()).not.toBeNull();
  });

  it("offers the configured model first in Settings, where empty means the CLI's", async () => {
    serve(SERVED);
    await show(<Field provider={null} initial="" emptyLabel="The CLI's model for the provider" />);
    expect(api.run).toHaveBeenCalledWith({ command: "llm_models", llm_provider: null });
    expect(options()).toEqual(["", ...SERVED, OTHER]);
    expect(selected()).toBe("");
  });
});
