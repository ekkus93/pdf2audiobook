import { describe, expect, it } from "vitest";
import type { CliConfig } from "../engine/types";
import { defaults, modelFor, requests, validate, type OptionsForm } from "./bookOptions";

export const CONFIG: CliConfig = {
  general: { output_dir: "/home/user/audiobooks" },
  llm: {
    enabled: true,
    provider: "ollama",
    max_context_tokens: 16384,
    max_output_tokens: 1024,
    allow_remote_content: false,
    ollama: { model: "qwen3.5:9b" },
    openai: { model: "gpt-4.1-mini" },
    llama_server: { model: "auto" },
  },
  tts: { provider: "kitten", kitten: { model: "mini", voice: "Jasper", speed: 1 }, piper: { voice: "", speed: 1 } },
  chapters: { min_boundary_confidence: 0.75 },
};

const FORM: OptionsForm = defaults(CONFIG, 12);

describe("defaults", () => {
  it("start from the CLI's own configuration", () => {
    expect(FORM).toEqual({
      llm: true,
      provider: "ollama",
      model: "qwen3.5:9b",
      contextTokens: "16384",
      outputTokens: "1024",
      remoteConsent: false,
      voice: "Jasper",
      speed: 1,
      allChapters: true,
      firstChapter: "1",
      lastChapter: "12",
      cover: null,
    });
  });

  it("name each provider's configured model", () => {
    expect(modelFor(CONFIG, "openai")).toBe("gpt-4.1-mini");
    expect(modelFor(CONFIG, "llama-server")).toBe("auto");
  });
});

describe("validate", () => {
  it("accepts the defaults", () => {
    expect(validate(FORM, 12)).toEqual({});
  });

  it("applies the CLI's LLM limits", () => {
    expect(validate({ ...FORM, model: " " }, 12).model).toBe("Enter a model name");
    expect(validate({ ...FORM, contextTokens: "400" }, 12).contextTokens).toBe("At least 512 tokens");
    expect(validate({ ...FORM, contextTokens: "lots" }, 12).contextTokens).toBe("At least 512 tokens");
    expect(validate({ ...FORM, outputTokens: "0" }, 12).outputTokens).toBe("At least 1 token");
    expect(validate({ ...FORM, outputTokens: "16300" }, 12).outputTokens).toMatch(/leave room/);
    expect(validate({ ...FORM, contextTokens: "262144", outputTokens: "32768" }, 12)).toEqual({});
  });

  it("needs consent before sending book text to OpenAI", () => {
    expect(validate({ ...FORM, provider: "openai" }, 12).remoteConsent).toMatch(/consent/);
    expect(validate({ ...FORM, provider: "openai", remoteConsent: true }, 12)).toEqual({});
  });

  it("ignores LLM fields when the LLM is off", () => {
    expect(validate({ ...FORM, llm: false, model: "", contextTokens: "1" }, 12)).toEqual({});
  });

  it("checks the speed and the chapter range", () => {
    expect(validate({ ...FORM, speed: 3.5 }, 12).speed).toBe("Between 0.1 and 3");
    const range = { ...FORM, allChapters: false };
    expect(validate({ ...range, firstChapter: "0" }, 12).firstChapter).toBe("From 1 to 12");
    expect(validate({ ...range, lastChapter: "13" }, 12).lastChapter).toBe("From 1 to 12");
    expect(validate({ ...range, firstChapter: "5", lastChapter: "3" }, 12).lastChapter).toBe(
      "Can't be before the first chapter",
    );
    expect(validate({ ...range, firstChapter: "2", lastChapter: "5" }, 12)).toEqual({});
  });
});

describe("requests", () => {
  it("turn the form into analyze and convert requests", () => {
    const built = requests("/books/a.pdf", { ...FORM, voice: "Luna", speed: 1.15, cover: "/art/c.png" }, "/out");
    const options = {
      output: "/out",
      llm: true,
      llm_provider: "ollama",
      llm_model: "qwen3.5:9b",
      llm_context_tokens: 16384,
      llm_output_tokens: 1024,
      allow_remote_content: null,
    };
    expect(built.analyze).toEqual({ command: "analyze", book: "/books/a.pdf", options });
    expect(built.convert).toEqual({
      command: "convert",
      book: "/books/a.pdf",
      options,
      convert: { voice: "Luna", speed: 1.15, cover: "/art/c.png", chapters: null },
    });
  });

  it("pass only --no-llm when the LLM is off, and consent only for OpenAI", () => {
    expect(requests("/b.pdf", { ...FORM, llm: false }, null).analyze).toEqual({
      command: "analyze",
      book: "/b.pdf",
      options: { output: null, llm: false },
    });
    const openai = requests("/b.pdf", { ...FORM, provider: "openai", model: "gpt-4.1-mini", remoteConsent: true }, null);
    expect(openai.analyze.command === "analyze" && openai.analyze.options.allow_remote_content).toBe(true);
  });

  it("send one chapter or a range", () => {
    const one = requests("/b.pdf", { ...FORM, allChapters: false, firstChapter: "3", lastChapter: "3" }, null).convert;
    expect(one.command === "convert" && one.convert.chapters).toEqual({ kind: "one", chapter: 3 });
    const range = requests("/b.pdf", { ...FORM, allChapters: false, firstChapter: "2", lastChapter: "5" }, null).convert;
    expect(range.command === "convert" && range.convert.chapters).toEqual({ kind: "range", first: 2, last: 5 });
  });
});
