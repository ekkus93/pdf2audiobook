import { describe, expect, it } from "vitest";
import type { CliConfig } from "../engine/types";
import { defaults, modelFor, requests, usesKitten2, validate, type OptionsForm } from "./bookOptions";

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
  it("keep the LLM as the book was last analyzed, ahead of the CLI's configuration", () => {
    expect(defaults(CONFIG, 4, {}, false).llm).toBe(false);
    expect(defaults({ ...CONFIG, llm: { ...CONFIG.llm, enabled: false } }, 4, {}, true).llm).toBe(true);
    expect(defaults(CONFIG, 4, {}, null).llm).toBe(CONFIG.llm.enabled);
  });

  it("use the app's Settings for voice, provider and model when set", () => {
    const form = defaults(CONFIG, 4, { default_voice: "Luna", llm_provider: "llama-server", llm_model: "local-model" });
    expect([form.voice, form.provider, form.model]).toEqual(["Luna", "llama-server", "local-model"]);
  });

  it("take the CLI's model for a preferred provider without a preferred model", () => {
    const form = defaults(CONFIG, 4, { llm_provider: "llama-server", llm_model: null, default_voice: null });
    expect([form.voice, form.provider, form.model]).toEqual(["Jasper", "llama-server", CONFIG.llm.llama_server.model]);
  });

  it("start from the CLI's own configuration", () => {
    expect(FORM).toEqual({
      voiceMode: "inherit", inheritedClone: false, inheritedReference: false, inheritedTranscript: false, inheritedKitten2: false,
      referenceAudio: "", referenceText: "", referenceTextFile: "",
      llm: true,
      provider: "ollama",
      model: "qwen3.5:9b",
      contextTokens: "16384",
      outputTokens: "1024",
      remoteConsent: false,
      voice: "Jasper",
      speed: 1,
      temperature: 0.2,
      allChapters: true,
      firstChapter: "1",
      lastChapter: "12",
      cover: null,
      verifyAudio: false,
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
      convert: { voice: "Luna", speed: 1.15, cover: "/art/c.png", verify_audio: false, chapters: null },
    });
  });

  it("verify the audio only when the box is ticked", () => {
    const off = requests("/b.pdf", FORM, null).convert;
    expect(off.command === "convert" && off.convert.verify_audio).toBe(false);
    const on = requests("/b.pdf", { ...FORM, verifyAudio: true }, null).convert;
    expect(on.command === "convert" && on.convert.verify_audio).toBe(true);
    // Analysis never verifies.
    expect(requests("/b.pdf", { ...FORM, verifyAudio: true }, null).analyze).not.toHaveProperty("convert");
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

describe("Kitten 2 temperature", () => {
  const kitten = (model: string, extra: Partial<CliConfig["tts"]["kitten"]> = {}): CliConfig => ({
    ...CONFIG,
    tts: { ...CONFIG.tts, kitten: { ...CONFIG.tts.kitten, model, ...extra } },
  });
  const profiled = (profile: NonNullable<CliConfig["tts"]["profiles"]>[string], base: CliConfig = CONFIG): CliConfig => ({
    ...base,
    tts: { ...base.tts, profiles: { Novel: profile } },
  });

  it("start from the profile, then the configuration, then 0.2", () => {
    expect(defaults(CONFIG, 3).temperature).toBe(0.2);
    expect(defaults(kitten("kitten2", { temperature: 0.4 }), 3).temperature).toBe(0.4);
    const book = profiled({ temperature: 0.25 }, kitten("kitten2", { temperature: 0.4 }));
    expect(defaults(book, 3, {}, null, "/books/Novel.pdf").temperature).toBe(0.25);
    expect(defaults(book, 3, {}, null, "/books/Other.pdf").temperature).toBe(0.4);
  });

  it("know when the book will use Kitten 2", () => {
    expect(usesKitten2(defaults(CONFIG, 3))).toBe(false);
    expect(usesKitten2(defaults(kitten("kitten2"), 3))).toBe(true);
    expect(usesKitten2(defaults(kitten("KittenML/kitten-tts-2"), 3))).toBe(true);
    expect(usesKitten2(defaults({ ...kitten("kitten2"), tts: { ...kitten("kitten2").tts, provider: "piper" } }, 3))).toBe(false);
    expect(usesKitten2(defaults(profiled({ kitten_model: "kitten2" }), 3, {}, null, "/b/Novel.pdf"))).toBe(true);
    expect(usesKitten2(defaults(profiled({ provider: "piper" }, kitten("kitten2")), 3, {}, null, "/b/Novel.pdf"))).toBe(false);
    expect(usesKitten2(defaults(profiled({ clone_voice: true }), 3, {}, null, "/b/Novel.pdf"))).toBe(true);
    expect(usesKitten2({ ...defaults(CONFIG, 3), voiceMode: "clone" })).toBe(true);
    const inheritedClone = defaults({ ...CONFIG, tts: { ...CONFIG.tts, voice_clone: { enabled: true, reference_audio: "/r.wav", reference_text_file: null } } }, 3);
    expect(usesKitten2(inheritedClone)).toBe(true);
    expect(usesKitten2({ ...inheritedClone, voiceMode: "builtin" })).toBe(false);
  });

  it("are checked against the CLI's range", () => {
    for (const temperature of [0.04, 1.51, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(validate({ ...FORM, temperature }, 12).temperature).toBe("Between 0.05 and 1.5");
    }
    expect(validate({ ...FORM, temperature: 0.05 }, 12)).toEqual({});
    expect(validate({ ...FORM, temperature: 1.5 }, 12)).toEqual({});
  });

  it("are sent only when Kitten 2 speaks the book", () => {
    const sent = (form: OptionsForm) => {
      const built = requests("/b.pdf", form, null).convert;
      return built.command === "convert" ? built.convert : null;
    };
    expect(sent({ ...FORM, temperature: 0.3 })).not.toHaveProperty("temperature");
    expect(sent({ ...defaults(kitten("kitten2"), 3), temperature: 0.3 })?.temperature).toBe(0.3);
    expect(sent({ ...FORM, voiceMode: "clone", referenceAudio: "/r.wav", temperature: 0.35 })?.temperature).toBe(0.35);
  });
});
