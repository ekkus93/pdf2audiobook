// End-to-end walkthrough of the desktop app (spec D9.d, TD10.01), through tauri-driver:
// add the README demo book, analyze it without the LLM, retitle chapter 1 in review and save,
// then convert with --dry-run. Plain W3C WebDriver over fetch; no test framework needed.
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

// The app runs this as its CLI. It is the real CLI, with --dry-run added to convert, so the
// walkthrough needs no speech model.
const cli = join(home, "pdf2audiobook");
writeFileSync(
  cli,
  `#!/bin/sh
set -e
first=1
for arg in "$@"; do
  if [ "$first" = 1 ]; then set --; first=0; fi
  set -- "$@" "$arg"
  if [ "$arg" = convert ]; then set -- "$@" --dry-run; fi
done
exec uv run --project ${JSON.stringify(REPO)} pdf2audiobook "$@"
`,
);
chmodSync(cli, 0o755);
writeFileSync(
  join(config, "io.github.ekkus93.pdf2audiobook", "settings.json"),
  JSON.stringify({ cli_path: cli, output_dir: out, theme: "dark", added_books: [] }),
);

// --- WebDriver ---

const env = { ...process.env, XDG_CONFIG_HOME: config, XDG_DATA_HOME: join(home, "data"), HF_HUB_OFFLINE: "1" };
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

const click = (id) => call("POST", s(`/element/${id}/click`), {});
const run = (script, args = []) => call("POST", s("/execute/sync"), { script, args });

/**
 * Saves the screen to the artifacts folder with ImageMagick, if it's installed. (WebKitWebDriver's
 * own screenshot command doesn't answer under Xvfb.)
 */
async function screenshot(name) {
  spawnSync("import", ["-window", "root", join(ARTIFACTS, `${name}.png`)], { timeout: 15_000 });
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
  await click(await find(button("Add book")));
  await sleep(2500);
  // GTK completes paths as they're typed; a fresh temporary folder has no look-alike siblings.
  const typed = spawnSync("xdotool", ["type", "--delay", "60", book], { encoding: "utf8" });
  if (typed.status !== 0) throw new Error(`xdotool: ${typed.stderr}`);
  await sleep(500);
  spawnSync("xdotool", ["key", "Return"]);
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

  step("convert with --dry-run");
  // The options start from the CLI's configuration again (LLM on); keep this book's analysis.
  await find("//h3[contains(., 'Analysis')]", 60);
  await llmOff();
  await click(await find(button("Convert to audio"), 60));
  await find("//*[contains(., 'Conversion finished')]", 180);
  await screenshot("5-converted");

  const workspace = readdirSync(out).find((name) => name.startsWith("lighthouse"));
  const manifest = JSON.parse(readFileSync(join(out, workspace, "manifest.json"), "utf8"));
  if (manifest.chapters[0].title !== NEW_TITLE) throw new Error(`chapter 1 is "${manifest.chapters[0].title}"`);
  if (!manifest.chapters[0].manually_approved) throw new Error("chapter 1 was not approved in review");
  step("passed: the book was added, analyzed, reviewed and converted (dry run)");
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
  rmSync(home, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
