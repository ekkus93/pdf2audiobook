// Stands in for the CLI's audio verification commands in the walkthrough (verification spec
// AV5.06): CI has no speech recognizer models, so `asr`, `verify-audio`, `audio-report` and
// `resynthesize` answer from the bridge's real-output fixtures instead, deterministically.
// Chapter 2 of the book is heard with an insertion that two models confirm; speaking it again
// clears it. Every argument the app sends is appended to `calls.jsonl` for the walkthrough to
// check. Usage (from the walkthrough's CLI wrapper): node fake_asr.mjs STATE_DIR CLI_ARGS...

import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FIXTURES = resolve(dirname(fileURLToPath(import.meta.url)), "../src-tauri/tests/fixtures");
const fixture = (name) => JSON.parse(readFileSync(join(FIXTURES, name), "utf8"));

const [state, ...argv] = process.argv.slice(2);
appendFileSync(join(state, "calls.jsonl"), `${JSON.stringify(argv)}\n`);
const saved = join(state, "audio_verification.json");

const words = argv.filter((arg) => !arg.startsWith("--"));
const positionals = argv.includes("--") ? argv.slice(argv.indexOf("--") + 1) : [];
const option = (name) => argv.filter((arg) => arg.startsWith(`${name}=`)).map((arg) => arg.slice(name.length + 1));
const print = (payload) => console.log(JSON.stringify({ ...payload, warnings: payload.warnings ?? [] }, null, 2));

function models() {
  const listed = fixture("asr-models.json");
  for (const model of listed.models) model.location = join(state, "asr", model.model);
  return listed;
}

/** A report for every chapter of `manifest`: chapter 2 flagged, unless it has been repaired. */
function report(manifest, repaired) {
  const real = fixture("audio-verification.json");
  const clean = real.chapters.find((chapter) => chapter.status === "no_mismatch_detected");
  const flagged = real.chapters.find((chapter) => chapter.status === "possible_mismatch");
  const count = JSON.parse(readFileSync(manifest, "utf8")).chapters.length;
  real.chapters = Array.from({ length: count }, (_, index) => {
    const number = index + 1;
    const base = number === 2 && !repaired ? flagged : clean;
    const chapter = structuredClone(base);
    chapter.number = number;
    if (number === 2 && !repaired) {
      // Within the walkthrough's six-second chapter files.
      chapter.flags = chapter.flags.map((flag, at) => ({ ...flag, start: 3.5 + at, end: 4.5 + at }));
    }
    return chapter;
  });
  real.summary = { chapters: count, by_status: {} };
  for (const chapter of real.chapters) real.summary.by_status[chapter.status] = (real.summary.by_status[chapter.status] ?? 0) + 1;
  return real;
}

const command = words.slice(0, 2).join(" ");
if (command === "asr list") {
  print(models());
} else if (command === "asr fetch") {
  print({ ...models(), fetched: [] });
} else if (words[0] === "verify-audio") {
  const result = report(positionals[0], false);
  writeFileSync(saved, JSON.stringify(result));
  print(result);
} else if (command === "audio-report show") {
  print({ schema_version: 1, report: existsSync(saved) ? JSON.parse(readFileSync(saved, "utf8")) : null, stale: [] });
} else if (command === "audio-report dismiss") {
  const result = JSON.parse(readFileSync(saved, "utf8"));
  const [chapter, flag] = [Number(option("--chapter")[0]), Number(option("--flag")[0])];
  const reviewed = !argv.includes("--undo");
  result.chapters.find((item) => item.number === chapter).flags[flag].reviewed = reviewed;
  writeFileSync(saved, JSON.stringify(result));
  print({ chapter, flag, reviewed });
} else if (words[0] === "resynthesize") {
  const chapters = option("--chapter").map(Number);
  const result = report(positionals[0], true);
  writeFileSync(saved, JSON.stringify(result));
  const audio = join(dirname(positionals[0]), "audio");
  print({
    mp3_files: chapters.map((number) => join(audio, `${String(number).padStart(3, "0")} - chapter.mp3`)),
    audio_verification: {
      report: "reports/audio_verification.json",
      chapters: chapters.map((number) => ({ number, status: "no_mismatch_detected", reason: null, partial: false, flags: 0 })),
    },
  });
} else {
  console.error(JSON.stringify({ ok: false, error: { type: "InputError", code: 2, message: "The walkthrough's stand-in doesn't know this command" } }));
  process.exit(2);
}
