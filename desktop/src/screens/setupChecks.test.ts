import { describe, expect, it } from "vitest";
import type { Doctor, EngineInfo, LlmCheck } from "../engine/types";
import { setupChecks } from "./setupChecks";

const ENGINE: EngineInfo = { version: "0.1.0", source: "on_path", command: "pdf2audiobook" };
const DOCTOR: Doctor = {
  version: "0.1.0",
  ffmpeg: true,
  tesseract: true,
  ocr_requested_languages: "eng",
  ocr_installed_languages: ["eng", "osd"],
  ocr_missing_languages: [],
  kitten_installed: true,
  piper_installed: false,
  llm_provider: "ollama",
  process_citations: true,
  process_equations: true,
  llm_timeout_seconds: 300,
  warnings: [],
};

function byId(doctor: Partial<Doctor>, engine: EngineInfo = ENGINE) {
  return Object.fromEntries(setupChecks(engine, { ...DOCTOR, ...doctor }).map((check) => [check.id, check]));
}

const OLLAMA: LlmCheck = {
  provider: "ollama",
  checked: true,
  model: "qwen3.5:9b",
  configured_context: 16384,
  output_tokens: 1024,
  chunk_tokens: 4000,
  estimated_tokens_needed: 9248,
  reachable: true,
  served_context: 262144,
  enough: true,
};

describe("setupChecks", () => {
  it("reports a complete setup in order, with Piper optional", () => {
    const checks = setupChecks(ENGINE, DOCTOR);
    expect(checks.map((check) => check.id)).toEqual(["cli", "ffmpeg", "tesseract", "kitten", "piper", "llm"]);
    expect(checks.map((check) => check.state)).toEqual(["ok", "ok", "ok", "ok", "optional", "optional"]);
    expect(checks[0].detail).toBe("Version 0.1.0, from your PATH.");
  });

  it("names where the CLI came from", () => {
    expect(byId({}, { ...ENGINE, source: "uv_project" }).cli.detail).toContain("a source checkout, through uv");
    expect(byId({}, { ...ENGINE, source: "configured" }).cli.detail).toContain("the path in Settings");
  });

  it("gives the exact install command for each missing program", () => {
    const checks = byId({ ffmpeg: false, tesseract: false, kitten_installed: false });
    expect(checks.ffmpeg).toMatchObject({ state: "attention", fix: "sudo apt install ffmpeg" });
    expect(checks.tesseract).toMatchObject({
      state: "attention",
      fix: "sudo apt install tesseract-ocr tesseract-ocr-eng",
    });
    expect(checks.kitten).toMatchObject({ state: "attention", fix: 'uv tool install ".[kitten]"' });
  });

  it("lists missing OCR languages as packages", () => {
    const check = byId({ ocr_requested_languages: "eng+deu+fra", ocr_missing_languages: ["deu", "fra"] }).tesseract;
    expect(check.detail).toBe("Missing the language data for deu, fra.");
    expect(check.fix).toBe("sudo apt install tesseract-ocr-deu tesseract-ocr-fra");
  });

  it("describes the LLM by provider, and Ollama only once checked", () => {
    expect(byId({ llm_provider: "disabled" }).llm.state).toBe("optional");
    expect(byId({ llm_provider: "openai" }).llm).toMatchObject({ state: "ok" });
    expect(byId({}).llm.detail).toBe("Uses Ollama. Check that its model has enough context.");
  });

  it("confirms an Ollama model with enough context", () => {
    const check = byId({ llm_check: OLLAMA }).llm;
    expect(check.state).toBe("ok");
    expect(check.detail).toContain("262,144 tokens");
  });

  it("explains a model served with too little context and how to fix it", () => {
    const check = byId({ llm_check: { ...OLLAMA, served_context: 4096, enough: false } }).llm;
    expect(check.state).toBe("attention");
    expect(check.detail).toContain("only 4,096 tokens; analysis needs about 9,248");
    expect(check.fix).toBe(
      "printf 'FROM qwen3.5:9b\\nPARAMETER num_ctx 262144\\n' > Modelfile && ollama create qwen35-256k -f Modelfile",
    );
  });

  it("points at the config when Ollama serves enough but the app is set lower", () => {
    const check = byId({ llm_check: { ...OLLAMA, configured_context: 8192, enough: false } }).llm;
    expect(check.state).toBe("attention");
    expect(check.detail).toContain("llm.max_context_tokens");
    expect(check.fix).toBeUndefined();
  });

  it("says how to start an unreachable Ollama", () => {
    const check = byId({ llm_check: { ...OLLAMA, reachable: false, served_context: null, enough: false } }).llm;
    expect(check).toMatchObject({ state: "attention", fix: "ollama pull qwen3.5:9b" });
    expect(check.detail).toContain("ollama serve");
  });
});
