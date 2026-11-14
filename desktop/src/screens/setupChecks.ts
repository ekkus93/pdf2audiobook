import type { Doctor, EngineInfo, LlmCheck } from "../engine/types";
import type { IconName } from "../theme/icons.generated";

export type CheckState = "ok" | "attention" | "optional";

export interface Check {
  id: string;
  title: string;
  state: CheckState;
  detail: string;
  /** An exact command that fixes the problem, when there is one. */
  fix?: string;
  icon: IconName;
}

const SOURCES: Record<EngineInfo["source"], string> = {
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
  return checks;
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
