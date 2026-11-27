import type { Doctor, EngineInfo, LlmCheck } from "../engine/types";
import type { IconName } from "../theme/icons.generated";

export type CheckState = "ok" | "attention" | "optional";

export interface Check {
  id: string;
  title: string;
  state: CheckState;
  detail: string;
  /** An exact command that fixes the problem, when there is one (developer engines only). */
  fix?: string;
  /** Something the app can do about it itself (the built-in engine). */
  action?: { kind: "add_languages"; languages: string[] };
  icon: IconName;
}

const SOURCES: Record<EngineInfo["source"], string> = {
  bundled: "the engine built into this app",
  configured: "the path in Settings",
  on_path: "your PATH",
  uv_project: "a source checkout, through uv",
};

/** The Setup screen's rows for a confirmed CLI and its `doctor --json` report (spec D4.1). */
export function setupChecks(engine: EngineInfo, doctor: Doctor): Check[] {
  const checks: Check[] = [
    {
      id: "cli",
      title: "pdf2audiobook",
      state: "ok",
      detail: `Version ${engine.version}, from ${SOURCES[engine.source]}.`,
      icon: "terminal",
    },
    doctor.ffmpeg
      ? { id: "ffmpeg", title: "FFmpeg", state: "ok", detail: "Makes MP3 and M4B files.", icon: "audio_file" }
      : {
          id: "ffmpeg",
          title: "FFmpeg",
          state: "attention",
          detail: "Needed to make MP3 and M4B files.",
          fix: "sudo apt install ffmpeg",
          icon: "audio_file",
        },
  ];
  if (!doctor.tesseract) {
    checks.push({
      id: "tesseract",
      title: "Tesseract OCR",
      state: "attention",
      detail: "Needed only for scanned pages; books with a text layer work without it.",
      fix: "sudo apt install tesseract-ocr tesseract-ocr-eng",
      icon: "description",
    });
  } else if (doctor.ocr_missing_languages.length > 0) {
    const packages = doctor.ocr_missing_languages.map((code) => `tesseract-ocr-${code}`).join(" ");
    checks.push({
      id: "tesseract",
      title: "Tesseract OCR",
      state: "attention",
      detail: `Missing the language data for ${doctor.ocr_missing_languages.join(", ")}.`,
      fix: `sudo apt install ${packages}`,
      icon: "description",
    });
  } else {
    checks.push({
      id: "tesseract",
      title: "Tesseract OCR",
      state: "ok",
      detail: `Reads scanned pages in ${doctor.ocr_requested_languages}.`,
      icon: "description",
    });
  }
  checks.push(
    doctor.kitten_installed
      ? { id: "kitten", title: "Kitten voices", state: "ok", detail: "The default voices are installed.", icon: "graphic_eq" }
      : {
          id: "kitten",
          title: "Kitten voices",
          state: "attention",
          detail: "The default voices aren't installed. Run this in the pdf2audiobook checkout:",
          fix: 'uv tool install ".[kitten]"',
          icon: "graphic_eq",
        },
    doctor.piper_installed
      ? { id: "piper", title: "Piper voices", state: "ok", detail: "The Piper CLI is installed.", icon: "graphic_eq" }
      : {
          id: "piper",
          title: "Piper voices",
          state: "optional",
          detail: "Optional. Piper is a second voice engine you can install separately.",
          icon: "graphic_eq",
        },
  );
  checks.push(llmCheck(doctor));
  return engine.source === "bundled" ? checks.map((check) => builtIn(check, doctor)) : checks;
}

/**
 * The same rows for the engine built into the app (self-contained app spec SC5): no terminal
 * commands. Built-in parts that are missing mean a damaged install; OCR languages download in
 * the app; LLM help is optional, so an unreachable Ollama is not a problem to fix.
 */
function builtIn(check: Check, doctor: Doctor): Check {
  const { fix: _command, ...row } = check;
  void _command;
  if (check.state !== "attention" && !(check.id === "llm" && doctor.llm_check && !doctor.llm_check.reachable)) return row;
  switch (check.id) {
    case "ffmpeg":
      return { ...row, detail: "The app's built-in FFmpeg is missing. Reinstall the app." };
    case "kitten":
      return { ...row, detail: "The app's built-in voices are missing. Reinstall the app." };
    case "tesseract":
      if (!doctor.tesseract) return { ...row, detail: "The app's built-in OCR data is missing. Reinstall the app." };
      return {
        ...row,
        detail: `OCR data for ${doctor.ocr_missing_languages.join(", ")} isn't downloaded yet. Each language is a small download.`,
        action: { kind: "add_languages", languages: doctor.ocr_missing_languages },
      };
    case "llm": {
      const report = doctor.llm_check;
      const model = report?.model ?? "the model";
      if (report && !report.reachable) {
        return {
          ...row,
          state: "optional",
          detail: `Ollama isn't running, so books are analyzed without an LLM, from their layout alone. LLM help is optional: to use it, install Ollama from ollama.com, start it with ${model}, then check again.`,
        };
      }
      if (report && (report.served_context ?? 0) < (report.estimated_tokens_needed ?? 0)) {
        return {
          ...row,
          detail: `Ollama serves ${model} with only ${(report.served_context ?? 0).toLocaleString("en-US")} tokens; analysis needs about ${(report.estimated_tokens_needed ?? 0).toLocaleString("en-US")}. Give the model a larger context in Ollama, or choose another model in the book options.`,
        };
      }
      return {
        ...row,
        detail: `Ollama serves enough, but pdf2audiobook is set to use only ${report?.configured_context?.toLocaleString("en-US")} tokens. Raise llm.max_context_tokens in Settings → CLI configuration.`,
      };
    }
    default:
      return row;
  }
}

function llmCheck(doctor: Doctor): Check {
  const base = { id: "llm", title: "LLM help", icon: "auto_stories" as const };
  if (doctor.llm_provider === "disabled") {
    return { ...base, state: "optional", detail: "Off. Books are analyzed without an LLM." };
  }
  const report = doctor.llm_check;
  if (doctor.llm_provider !== "ollama") {
    return { ...base, state: "ok", detail: `Uses ${doctor.llm_provider}. Only Ollama can be checked here.` };
  }
  if (!report) {
    return { ...base, state: "optional", detail: "Uses Ollama. Check that its model has enough context." };
  }
  return ollamaResult(report);
}

function ollamaResult(report: LlmCheck): Check {
  const base = { id: "llm", title: "LLM help", icon: "auto_stories" as const };
  const model = report.model ?? "the model";
  if (!report.reachable) {
    return {
      ...base,
      state: "attention",
      detail: `Ollama didn't answer for ${model}. Make sure Ollama is running (ollama serve) and the model is pulled:`,
      fix: `ollama pull ${model}`,
    };
  }
  if (report.enough) {
    return {
      ...base,
      state: "ok",
      detail: `Ollama serves ${model} with ${report.served_context?.toLocaleString("en-US")} tokens of context, enough for analysis.`,
    };
  }
  const served = report.served_context ?? 0;
  const needed = report.estimated_tokens_needed ?? 0;
  if (served >= needed) {
    return {
      ...base,
      state: "attention",
      detail: `Ollama serves enough, but pdf2audiobook is set to use only ${report.configured_context?.toLocaleString("en-US")} tokens. Raise llm.max_context_tokens in its config.`,
    };
  }
  const variant = `${model.split(":")[0].replace(/[^a-zA-Z0-9]/g, "")}-256k`;
  return {
    ...base,
    state: "attention",
    detail: `Ollama serves ${model} with only ${served.toLocaleString("en-US")} tokens; analysis needs about ${needed.toLocaleString("en-US")}. Create a variant with a larger context, then choose it in the book options:`,
    fix: `printf 'FROM ${model}\\nPARAMETER num_ctx 262144\\n' > Modelfile && ollama create ${variant} -f Modelfile`,
  };
}
