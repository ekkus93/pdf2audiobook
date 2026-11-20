// End-to-end walkthrough of the desktop app (spec D9.d, TD10.01), through tauri-driver:
// add the README demo book, analyze it without the LLM, retitle chapter 1 in review and save,
// then convert with --dry-run; then check the audio, listen at a flagged passage, mark it
// reviewed and speak that chapter again (audio verification AV5.06; the speech recognizers are
// stood in for by e2e/fake_asr.mjs). Plain W3C WebDriver over fetch; no test framework needed.
// E2E_DRY_RUN=0 converts with real speech instead (manual acceptance, TD10.05; needs Kitten).
//
//   E2E_APP=src-tauri/target/release/pdf2audiobook-desktop \
//   E2E_NATIVE_DRIVER=/usr/bin/WebKitWebDriver node e2e/walkthrough.mjs
//
// Needs an X display (Xvfb in CI), xdotool for the native file dialog, uv and this checkout.

import { spawn, spawnSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DESKTOP = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = resolve(DESKTOP, "..");
const APP = resolve(DESKTOP, process.env.E2E_APP ?? "src-tauri/target/release/pdf2audiobook-desktop");
const NATIVE_DRIVER = process.env.E2E_NATIVE_DRIVER ?? "/usr/bin/WebKitWebDriver";
const TAURI_DRIVER = process.env.E2E_TAURI_DRIVER ?? "tauri-driver";
const ARTIFACTS = resolve(process.env.E2E_ARTIFACTS ?? join(DESKTOP, "e2e", "artifacts"));
const PORT = 4444;
const NEW_TITLE = "The Keeper (reviewed)";
const CLONE = process.env.E2E_CLONE === "1";
const DRY_RUN = process.env.E2E_DRY_RUN !== "0";

const shellQuote = (value) => "'" + value.replaceAll("'", "'\\''") + "'";
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

function step(text) {
  console.log(`e2e: ${text}`);
}

// --- A throwaway home for the app: settings, the demo book and a CLI that adds --dry-run. ---

const home = mkdtempSync(join(tmpdir(), "p2a-e2e-"));
const config = join(home, "config");
const out = join(home, "out");
const book = join(home, "lighthouse.pdf");
mkdirSync(join(config, "io.github.ekkus93.pdf2audiobook"), { recursive: true });
mkdirSync(out);
mkdirSync(ARTIFACTS, { recursive: true });

const made = spawnSync("uv", ["run", "--project", REPO, "python", "scripts/readme_screenshots/make_demo_pdf.py", book], {
  cwd: REPO,
  encoding: "utf8",
});
if (made.status !== 0) throw new Error(`demo book: ${made.stderr}`);

// The app runs this as its CLI. It is the real CLI, with --dry-run added to convert (unless
// E2E_DRY_RUN=0), so the walkthrough needs no speech model.
const cli = join(home, "pdf2audiobook");
const asrState = join(home, "asr-state");
mkdirSync(asrState);
writeFileSync(
  cli,
  `#!/bin/sh
set -e
case " $* " in
  *" --clone-voice "*) exec uv run --project ${shellQuote(REPO)} python ${shellQuote(join(DESKTOP, "e2e", "fake_clone.py"))} ${shellQuote(asrState)} "$@" ;;
esac
for arg in "$@"; do
  case "$arg" in
    --) break ;;
    asr|verify-audio|audio-report|resynthesize) exec node ${shellQuote(join(DESKTOP, "e2e", "fake_asr.mjs"))} ${shellQuote(asrState)} "$@" ;;
  esac
done
first=1
for arg in "$@"; do
  if [ "$first" = 1 ]; then set --; first=0; fi
  set -- "$@" "$arg"
  if [ "$arg" = convert ] && [ ${DRY_RUN ? 1 : 0} = 1 ]; then set -- "$@" --dry-run; fi
done
exec uv run --project ${shellQuote(REPO)} pdf2audiobook "$@"
`,
);
chmodSync(cli, 0o755);
writeFileSync(
  join(config, "io.github.ekkus93.pdf2audiobook", "settings.json"),
  JSON.stringify({ cli_path: cli, output_dir: out, theme: "dark", added_books: [] }),
);

// --- WebDriver ---

const env = { ...process.env, XDG_CONFIG_HOME: config, XDG_DATA_HOME: join(home, "data"), XDG_CACHE_HOME: join(home, "cache"), HF_HUB_OFFLINE: "1" };
const driver = spawn(TAURI_DRIVER, ["--port", String(PORT), "--native-driver", NATIVE_DRIVER], {
  env,
  stdio: ["ignore", "inherit", "inherit"],
});

async function call(method, path, body) {
  const response = await fetch(`http://127.0.0.1:${PORT}${path}`, {
    signal: AbortSignal.timeout(120_000),
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${method} ${path}: ${JSON.stringify(payload.value ?? payload)}`);
  return payload.value;
}

let session = null;
const ELEMENT = "element-6066-11e4-a52e-4f735466cecf";
const s = (path) => `/session/${session}${path}`;

async function find(xpath, seconds = 30) {
  const deadline = Date.now() + seconds * 1000;
  for (;;) {
    const found = await call("POST", s("/elements"), { using: "xpath", value: xpath });
    if (found.length) return found[0][ELEMENT];
    if (Date.now() > deadline) throw new Error(`not found: ${xpath}`);
    await sleep(250);
  }
}

const click = async (id) => {
  await run("arguments[0].scrollIntoView({block:'center',inline:'center',behavior:'instant'});", [{[ELEMENT]:id}]);
  await sleep(100);
  return call("POST", s(`/element/${id}/click`), {});
};
const run = (script, args = []) => call("POST", s("/execute/sync"), { script, args });

/**
 * Saves the screen to the artifacts folder with ImageMagick, if it's installed. (WebKitWebDriver's
 * own screenshot command doesn't answer under Xvfb.)
 */
async function screenshot(name) {
  const display = spawnSync("xdpyinfo", [], { encoding: "utf8" });
  const dimensions = (display.stdout ?? "").match(/dimensions:\s+(\d+x\d+)\s+pixels/)?.[1] ?? "1280x800";
  spawnSync("ffmpeg", ["-nostdin", "-v", "error", "-f", "x11grab", "-video_size", dimensions, "-i", process.env.DISPLAY, "-frames:v", "1", "-y", join(ARTIFACTS, `${name}.png`)], { timeout: 15_000 });
}

/**
 * A Material button by its label: its text, or for an icon-labelled one its `aria-label`
 * (which Material keeps as `data-aria-label`).
 */
const button = (label) =>
  `//*[self::md-filled-button or self::md-filled-tonal-button or self::md-outlined-button or self::md-text-button or self::md-fab][contains(., ${JSON.stringify(label)}) or @aria-label=${JSON.stringify(label)} or @data-aria-label=${JSON.stringify(label)}]`;

/** Turns off "Use an LLM" on the book page if it's on. */
async function llmOff() {
  const llm = await find("//md-switch");
  if (await run("return arguments[0].selected;", [{ [ELEMENT]: llm }])) await click(llm);
}

/** Visible X windows, by ID (the file chooser shows up as a new one). */
function visibleWindows() {
  const found = spawnSync("xdotool", ["search", "--onlyvisible", "--name", "."], { encoding: "utf8" });
  return new Set(found.stdout.split(/\s+/).filter(Boolean));
}

/**
 * Adds the demo book through the native file chooser. The chooser can be slow to appear and to
 * fill its file list under CI's AppImage run, so this waits for the window itself, lets it load,
 * and tries again (closing the chooser first) if the book card doesn't appear.
 */
async function addDemoBook() {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const before = visibleWindows();
    await click(await find(button("Add book")));
    let dialog = null;
    for (let tries = 0; tries < 120 && !dialog; tries++) {
      dialog = [...visibleWindows()].find((id) => !before.has(id)) ?? null;
      if (!dialog) await sleep(250);
    }
    if (!dialog) throw new Error("the file chooser did not open");
    spawnSync("xdotool", ["windowactivate", "--sync", dialog]);
    spawnSync("xdotool", ["windowfocus", "--sync", dialog]);
    // GTK completes paths as they're typed; a fresh temporary folder has no look-alike siblings.
    await sleep(3000);
    spawnSync("xdotool", ["key", "ctrl+l"]);
    await sleep(200);
    const typed = spawnSync("xdotool", ["type", "--delay", "60", book], { encoding: "utf8" });
    if (typed.status !== 0) throw new Error(`xdotool: ${typed.stderr}`);
    await sleep(500);
    spawnSync("xdotool", ["key", "Return"]);
    const added = await findOptional(
      "//li[contains(@class, 'book-card')][contains(., 'lighthouse')]",
      20,
    );
    if (added) return;
    step(`  the book did not appear (attempt ${attempt}); trying again`);
    spawnSync("xdotool", ["key", "Escape"]);
    await sleep(1000);
  }
  throw new Error("the demo book was not added after 3 attempts");
}

async function findOptional(xpath, seconds) {
  try {
    return await find(xpath, seconds);
  } catch {
    return null;
  }
}

async function main() {
  for (let attempt = 0; ; attempt++) {
    try {
      await call("GET", "/status");
      break;
    } catch (error) {
      if (attempt > 100) throw error;
      await sleep(100);
    }
  }
  session = (
    await call("POST", "/session", {
      capabilities: { alwaysMatch: { browserName: "wry", "tauri:options": { application: APP } } },
    })
  ).sessionId;
  const main = await call("GET", s("/window"));

  step("the library starts empty");
  await find("//*[contains(., 'No books yet')]", 60);
  await screenshot("1-library");

  step("add the demo book through the file dialog");
  await addDemoBook();
  const card = await find(
    "//li[contains(@class, 'book-card')][contains(., 'lighthouse')]//button[contains(@class, 'book-open')]",
    30,
  );
  await screenshot("2-added");

  step("analyze it without the LLM");
  await click(card);
  await find("//h3[contains(., 'Analysis')]", 60);
  await llmOff();
  await click(await find(button("Analyze")));
  await find("//*[contains(., 'Analysis finished')]", 180);
  await screenshot("3-analyzed");

  step("review: retitle chapter 1 and save");
  await click(await find(button("Back to the book")));
  await click(await find(button("Review chapters"), 60));
  let review = null;
  for (let attempt = 0; attempt < 120 && !review; attempt++) {
    const handles = await call("GET", s("/window/handles"));
    review = handles.find((handle) => handle !== main) ?? null;
    if (!review) await sleep(250);
  }
  if (!review) throw new Error("the review window did not open");
  await call("POST", s("/window"), { handle: review });
  const title = await find("(//article//input[@name='title'])[1]", 60);
  await call("POST", s(`/element/${title}/clear`), {});
  await call("POST", s(`/element/${title}/value`), { text: NEW_TITLE });
  await click(await find("//button[@id='save']"));
  await find("//*[@id='status'][contains(., 'Saved')]", 60);
  await screenshot("4-review-saved");
  // Close it as a user would, so the app stops the review server and frees the book.
  await call("POST", s("/window"), { handle: main });
  const reviewWindow = spawnSync("xdotool", ["search", "--name", "^Review chapters"], { encoding: "utf8" })
    .stdout.trim()
    .split("\n")[0];
  if (!reviewWindow) throw new Error("the review window was not found on the display");
  const closed = spawnSync(
    "uv",
    ["run", "--no-project", "--with", "python-xlib", "python", join(DESKTOP, "e2e", "close_window.py"), reviewWindow],
    { encoding: "utf8" },
  );
  if (closed.status !== 0) throw new Error(`closing the review window: ${closed.stderr}`);
  for (let attempt = 0; ; attempt++) {
    const handles = await call("GET", s("/window/handles"));
    if (!handles.includes(review)) break;
    if (attempt > 120) throw new Error("the review window did not close");
    await sleep(250);
  }
  // The review button is enabled again once the app has seen the window close.
  await find(`${button("Review chapters")}[not(@disabled)]`, 30);

  step(DRY_RUN ? "convert with --dry-run" : "convert with real speech");
  // The book was analyzed without the LLM, so its options must start with it off.
  await find("//h3[contains(., 'Analysis')]", 60);
  const llm = await find("//md-switch");
  if (await run("return arguments[0].selected;", [{ [ELEMENT]: llm }])) {
    throw new Error("the LLM is on for a book analyzed without it");
  }
  await click(await find(button("Convert to audio"), 60));
  await find("//*[contains(., 'Conversion finished')]", DRY_RUN ? 180 : 1800);
  await screenshot("5-converted");

  const workspace = readdirSync(out).find((name) => name.startsWith("lighthouse"));
  const manifest = JSON.parse(readFileSync(join(out, workspace, "manifest.json"), "utf8"));
  if (manifest.chapters[0].title !== NEW_TITLE) throw new Error(`chapter 1 is "${manifest.chapters[0].title}"`);
  if (!manifest.chapters[0].manually_approved) throw new Error("chapter 1 was not approved in review");
  if (!DRY_RUN) {
    const audio = join(out, workspace, "audio");
    const mp3s = readdirSync(audio).filter((name) => name.endsWith(".mp3")).sort();
    if (mp3s.length !== manifest.chapters.length) {
      throw new Error(`${mp3s.length} MP3s for ${manifest.chapters.length} chapters`);
    }
    for (const name of mp3s) {
      const probe = spawnSync(
        "ffprobe",
        ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", join(audio, name)],
        { encoding: "utf8" },
      );
      step(`  ${name}: ${Number(probe.stdout.trim()).toFixed(1)} s`);
    }
  }
  await audioCheck(workspace, manifest.chapters.length);
  if (CLONE) await cloneCheck(workspace);
  step(
    `passed: the book was added, analyzed, reviewed, converted${DRY_RUN ? " (dry run)" : " with real speech"}, checked and repaired`,
  );
}

/** Checks the audio, listens at the flagged passage, marks it reviewed and speaks it again. */
async function audioCheck(workspace, chapters) {
  step("audio check: verify the book's audio");
  const audio = join(out, workspace, "audio");
  if (DRY_RUN) {
    // A dry run makes no MP3s; give each chapter a short silent one to play.
    mkdirSync(audio, { recursive: true });
    const silence = readFileSync(join(DESKTOP, "e2e", "fixtures", "silence.mp3"));
    for (let number = 1; number <= chapters; number++) {
      writeFileSync(join(audio, `${String(number).padStart(3, "0")} - Chapter ${number}.mp3`), silence);
    }
  }
  await click(await find(button("Back to the book")));
  await click(await find(`${button("Verify existing audio")}[not(@disabled)]`, 60));
  await find("//*[contains(., 'Audio check finished')]", 120);
  await click(await find(button("Back to the book")));
  const flagged = "//li[contains(@aria-label, 'Chapter 2: Possible mismatch')]";
  await find(`${flagged}[contains(., 'heard by Wav2Vec2 and Vosk')]`, 60);
  await run("document.querySelector('.check-possible_mismatch').scrollIntoView({ block: 'center', behavior: 'instant' });");
  await sleep(500);
  await screenshot("6-flagged");

  step("audio check: listen at the flagged passage");
  await click(await find(`(${flagged}${button("Listen")})[1]`));
  await find("//*[@aria-label='Player'][contains(., 'Chapter 2')]", 30);
  // Logged, not asserted: a display without a sound device may not play at all.
  // (The AppImage's media element may have no time at all; WebDriver can't return NaN.)
  let position = null;
  for (let attempt = 0; attempt < 40 && !(position >= 1.4); attempt++) {
    await sleep(250);
    position = await run(
      "const a = document.querySelector('[data-testid=player-audio]'); const t = a ? a.currentTime : NaN; return Number.isFinite(t) ? t : null;",
    );
  }
  step(
    position === null
      ? "  the player couldn't load the audio on this display"
      : `  the player is at ${position.toFixed(2)} s (the passage starts at 3.5 s; listening starts 2 s before)`,
  );

  step("audio check: mark it reviewed");
  await click(await find(`(${flagged}${button("Sounds right")})[1]`));
  await find(`${flagged}[contains(., '· reviewed')]`, 30);

  step("audio check: speak chapter 2 again");
  await click(await find(`${flagged}${button("Speak again")}`));
  await click(await find(`//md-dialog[@open]${button("Speak again")}`, 30));
  await find("//*[contains(., 'Chapters spoken again')]", 120);
  await click(await find(button("Back to the book")));
  await find(`//*[contains(., '${chapters} chapters checked · ${chapters} with no mismatch detected')]`, 60);
  const remaining = await call("POST", s("/elements"), { using: "xpath", value: flagged });
  if (remaining.length) throw new Error("chapter 2 is still flagged after speaking it again");
  await run("document.querySelector('.audio-check').scrollIntoView({ block: 'center', behavior: 'instant' });");
  await sleep(500);
  await screenshot("7-repaired");

  const calls = readFileSync(join(asrState, "calls.jsonl"), "utf8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  const sent = (word) => calls.find((args) => args.includes(word));
  const resynthesize = sent("resynthesize");
  const dismiss = sent("dismiss");
  if (!sent("verify-audio")) throw new Error("verify-audio was never run");
  if (!resynthesize || !resynthesize.includes("--chapter=2") || !resynthesize.includes("--verify-audio")) {
    throw new Error(`resynthesize was sent as ${JSON.stringify(resynthesize)}`);
  }
  if (!dismiss || !dismiss.includes("--chapter=2") || !dismiss.includes("--flag=0")) {
    throw new Error(`dismiss was sent as ${JSON.stringify(dismiss)}`);
  }
}

/** Real CLI/MP3 transactions with synthetic speech, through the native clone controls. */
async function cloneCheck(workspace) {
  step("cloning: select a reference through the native file picker");
  const prepared = spawnSync("uv", ["run", "--project", REPO, "python", join(DESKTOP, "e2e", "fake_clone.py"), asrState, "--prepare"], { encoding: "utf8" });
  if (prepared.status !== 0) throw new Error(`synthetic reference: ${prepared.stderr}`);
  const selection = await find("//md-outlined-select[.//*[contains(text(), 'Clone a voice (KittenTTS 2)')]]");
  await run("arguments[0].value='clone'; arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", [{[ELEMENT]:selection}]);
  await run("document.querySelector('.clone-controls').scrollIntoView({block:'center',behavior:'instant'});");
  const before = visibleWindows();
  await click(await find(button("Choose recording")));
  let picked = false;
  for (let attempt=0; attempt<3 && !picked; attempt++) {
    let dialog = null;
    for (let n=0; n<100 && !dialog; n++) {
      dialog = [...visibleWindows()].find((id)=>!before.has(id)) ?? null;
      if (!dialog) await sleep(100);
    }
    if (!dialog) throw new Error("reference file chooser did not open");
    spawnSync("xdotool", ["windowfocus", "--sync", dialog]);
    spawnSync("xdotool", ["key", "ctrl+l"]); await sleep(500);
    spawnSync("xdotool", ["key", "ctrl+a"]);
    spawnSync("xdotool", ["type", "--clearmodifiers", "--delay", "60", join(asrState,"reference.wav")]);
    await sleep(500); spawnSync("xdotool", ["key", "Return"]);
    for (let n=0; n<100 && !picked; n++) {
      picked = await run("return [...document.querySelectorAll('md-outlined-text-field')].some((field)=>field.label==='Reference recording' && field.value===arguments[0]);", [join(asrState,"reference.wav")]);
      if (!picked) await sleep(100);
    }
  }
  if (!picked) throw new Error("reference picker did not return the chosen recording");
  const transcript = await find("//textarea[contains(@id, 'r')]");
  await call("POST", s(`/element/${transcript}/value`), {text:"Synthetic reference transcript."});
  await screenshot("8-clone-options");
  const originalTheme = await run("const theme=document.documentElement.dataset.theme; document.documentElement.dataset.theme='light'; return theme;");
  await screenshot("8-clone-options-light");
  await run("document.documentElement.dataset.theme=arguments[0] ?? 'dark';", [originalTheme]);
  await click(await find(button("Convert to audio")));
  await find("//*[contains(., 'Conversion finished')]", 180);
  const audio = join(out,workspace,"audio");
  const sidecars = readdirSync(audio).filter((name)=>name.endsWith(".cache.json"));
  if (!sidecars.length || sidecars.some((name)=>!JSON.parse(readFileSync(join(audio,name),"utf8")).rendering_inputs.voice_clone)) throw new Error("cloned MP3 sidecars missing");
  const beforeResume = readFileSync(join(asrState,"generation.jsonl"),"utf8");
  await click(await find(button("Back to the book")));
  await click(await find(button("Convert to audio")));
  await find("//*[contains(., 'Conversion finished')]", 180);
  if (readFileSync(join(asrState,"generation.jsonl"),"utf8") !== beforeResume) throw new Error("clone resume repeated synthesis");
  await click(await find(button("Back to the book")));
  // Introduce one verification flag via the existing deterministic ASR fixture.
  rmSync(join(asrState,"repaired"), {force:true});
  await click(await find(`${button("Verify existing audio")}[not(@disabled)]`));
  await find("//*[contains(., 'Audio check finished')]",120);
  await click(await find(button("Back to the book")));
  const retry = await find("//li[contains(@aria-label, 'Chapter 2:')]"+button("Speak again"));
  await click(retry);
  await click(await find("//md-dialog[@open]"+button("Speak again")));
  await find("//*[contains(., 'Chapters spoken again')]",180);
  await screenshot("9-clone-repaired");
  if (!readdirSync(join(audio,".backup")).some((name)=>name.startsWith("002") && name.endsWith(".mp3"))) throw new Error("clone repair backup missing");
  await click(await find(button("Back to the book")));
  writeFileSync(join(asrState,"slow"),"");
  // Force a changed transcript so the next conversion must synthesize.
  const draft = await find("//textarea");
  await call("POST", s(`/element/${draft}/clear`), {});
  await call("POST", s(`/element/${draft}/value`), {text:"Another synthetic transcript."});
  await click(await find(button("Convert to audio")));
  for (let n=0; n<300 && !readdirSync(asrState).includes("inference-started"); n++) await sleep(100);
  await click(await find(button("Stop")));
  await find("//*[contains(., 'The run stopped') or contains(., 'Stopped')]",60);
  // Typed transcript drafts and canonical reference snapshots must both be gone.
  const privateFolders = [join(home,"cache/pdf2audiobook/desktop-voice"),join(home,"cache/pdf2audiobook/private-voice")];
  for (const folder of privateFolders) {
    try { if (readdirSync(folder).some((name)=>/^(draft-|job-)/.test(name))) throw new Error("private clone files survived cancellation"); }
    catch(error) { if (error.code !== "ENOENT") throw error; }
  }
  await screenshot("10-clone-cancelled");
  step("cloning passed: picker, typed draft, real CLI synthesis/MP3s, resume, repair, cancellation and cleanup (synthetic backend)");
}

let failed = false;
try {
  await main();
} catch (error) {
  failed = true;
  console.error(`e2e: FAILED: ${error.message}`);
  if (session) await screenshot("failure").catch(() => undefined);
} finally {
  if (session) await call("DELETE", `/session/${session}`).catch(() => undefined);
  driver.kill();
  // The app may still be writing its logs for a moment after the session closes; retry, and
  // report rather than fail a run that already passed.
  try {
    rmSync(home, { recursive: true, force: true, maxRetries: 20, retryDelay: 250 });
  } catch (error) {
    console.error(`e2e: could not remove ${home}: ${error.message}`);
  }
}
process.exit(failed ? 1 : 0);
