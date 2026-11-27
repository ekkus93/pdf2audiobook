import { useEffect, useState } from "react";
import { errorMessage, run } from "../engine/api";
import type { AddonLanguages, AddonName, AddonsList, Request } from "../engine/types";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { Icon } from "../ui/Icon";
import { IconButton } from "../ui/IconButton";
import { Select } from "../ui/Select";

/**
 * What each add-on downloads (self-contained app spec SC3), shown before asking. Sizes are disk
 * space measured on 2026-11-26; packages shared with the other add-on are installed once.
 */
export const ADDONS: Record<AddonName, { title: string; purpose: string; total: string; parts: string[] }> = {
  kitten2: {
    title: "Voice cloning and Kitten 2",
    purpose: "Speak books in a voice cloned from a recording, or with the larger Kitten 2 voices.",
    total: "about 3.2 GB",
    parts: [
      "Program packages, including PyTorch for the processor (no graphics card needed), about 1.6 GB, from the Python Package Index and the PyTorch download site",
      "The Kitten 2 voice model, 1.6 GB, from Hugging Face",
    ],
  },
  "audio-check": {
    title: "Audio checking (speech recognizers)",
    purpose: "Listen to finished chapters with three speech recognizers and flag passages that may not match the text.",
    total: "about 3.2 GB",
    parts: [
      "Program packages, including PyTorch for the processor, about 1.2 GB, from the Python Package Index and the PyTorch download site",
      "The Whisper (1.5 GB), wav2vec 2.0 (0.4 GB) and Vosk (0.1 GB) models, from their publishers",
    ],
  },
};

type Phase = { phase: "idle" } | { phase: "working" } | { phase: "failed"; message: string };

async function attempt<T>(request: Request): Promise<{ ok: true; result: T } | { ok: false; message: string }> {
  try {
    const outcome = await run<T>(request);
    if (outcome.outcome === "success") return { ok: true, result: outcome.result };
    return { ok: false, message: outcome.outcome === "failed" ? outcome.error.message : "The engine returned an unreadable result" };
  } catch (error) {
    return { ok: false, message: errorMessage(error) };
  }
}

/** Asks before downloading an add-on, then installs it (the engine checks every file's hash). */
export function AddonDialog({
  addon,
  open,
  onClose,
  onInstalled,
}: {
  addon: AddonName;
  open: boolean;
  onClose: () => void;
  onInstalled: () => void;
}) {
  const info = ADDONS[addon];
  const [state, setState] = useState<Phase>({ phase: "idle" });
  const install = async () => {
    setState({ phase: "working" });
    const done = await attempt({ command: "addons_install", addon });
    if (done.ok) {
      setState({ phase: "idle" });
      onInstalled();
      onClose();
    } else {
      setState({ phase: "failed", message: done.message });
    }
  };
  const working = state.phase === "working";
  return (
    <Dialog
      open={open}
      headline={`Install ${info.title}?`}
      onClose={() => !working && onClose()}
      actions={
        <>
          <Button variant="text" onClick={onClose} disabled={working}>
            Not now
          </Button>
          <Button icon="download" onClick={() => void install()} disabled={working}>
            {working ? "Downloading and installing…" : "Download and install"}
          </Button>
        </>
      }
    >
      <p className="body-medium">{info.purpose}</p>
      <p className="body-medium">
        This downloads {info.total} once, less if the other add-on is already installed, and keeps it in your user data folder. Every file
        is checked against its pinned checksum. No book text leaves this computer.
      </p>
      <ul className="body-medium">
        {info.parts.map((part) => (
          <li key={part}>{part}</li>
        ))}
      </ul>
      {working ? <p className="body-medium" role="status">This can take several minutes on a slow connection.</p> : null}
      {state.phase === "failed" ? (
        <p className="body-medium audio-problem" role="alert">
          {state.message}
        </p>
      ) : null}
    </Dialog>
  );
}

/** Loads `addons list`; null until known or when it can't be read. */
export function useAddons(active = true): { list: AddonsList | null; reload: () => void } {
  const [list, setList] = useState<AddonsList | null>(null);
  const [attemptNumber, setAttempt] = useState(0);
  useEffect(() => {
    if (!active) return;
    let current = true;
    void attempt<AddonsList>({ command: "addons_list" }).then((done) => {
      if (current) setList(done.ok ? done.result : null);
    });
    return () => {
      current = false;
    };
  }, [active, attemptNumber]);
  return { list, reload: () => setAttempt((value) => value + 1) };
}

/** Each add-on with Install… or Remove (Setup and Settings). Empty outside the built-in engine. */
export function AddonsPanel({ onChange }: { onChange?: () => void }) {
  const { list, reload } = useAddons();
  const [installing, setInstalling] = useState<AddonName | null>(null);
  const [problem, setProblem] = useState("");
  if (!list?.available) return null;
  const changed = () => {
    reload();
    onChange?.();
  };
  const remove = async (addon: AddonName) => {
    setProblem("");
    const done = await attempt({ command: "addons_remove", addon });
    if (!done.ok) setProblem(done.message);
    changed();
  };
  return (
    <div className="addons">
      <h3 className="title-medium">Optional add-ons</h3>
      <ul className="check-list" aria-label="Add-ons">
        {list.addons.map((addon) => (
          <li key={addon.name} className="check-row">
            <Icon name={addon.installed ? "check_circle" : "download"} filled={addon.installed} />
            <div>
              <div className="title-small">{ADDONS[addon.name]?.title ?? addon.title}</div>
              <p className="body-small on-surface-variant">
                {addon.installed ? "Installed" : "Not installed"} · {ADDONS[addon.name]?.purpose}
              </p>
            </div>
            {addon.installed ? (
              <Button variant="text" icon="delete" onClick={() => void remove(addon.name)}>
                Remove
              </Button>
            ) : (
              <Button variant="tonal" icon="download" onClick={() => setInstalling(addon.name)}>
                Install…
              </Button>
            )}
          </li>
        ))}
      </ul>
      {list.addons.some((addon) => addon.older_version_installed) ? (
        <p className="body-small on-surface-variant">
          Add-ons installed for an earlier version of the app are no longer used. Install them again here.
        </p>
      ) : null}
      {problem ? (
        <p className="body-medium audio-problem" role="alert">
          {problem}
        </p>
      ) : null}
      {installing ? (
        <AddonDialog addon={installing} open onClose={() => setInstalling(null)} onInstalled={changed} />
      ) : null}
    </div>
  );
}

/** OCR languages: the built-in ones, plus any the user adds (spec SC4). */
export function OcrLanguages() {
  const [languages, setLanguages] = useState<AddonLanguages | null>(null);
  const [choice, setChoice] = useState("");
  const [state, setState] = useState<Phase>({ phase: "idle" });
  useEffect(() => {
    let current = true;
    void attempt<AddonLanguages>({ command: "addon_languages" }).then((done) => {
      if (current && done.ok) setLanguages(done.result);
    });
    return () => {
      current = false;
    };
  }, []);
  if (!languages || languages.available.length === 0) return null;
  const change = async (request: Request) => {
    setState({ phase: "working" });
    const done = await attempt<AddonLanguages>(request);
    if (done.ok) {
      setLanguages(done.result);
      setChoice("");
      setState({ phase: "idle" });
    } else {
      setState({ phase: "failed", message: done.message });
    }
  };
  const addable = languages.available.filter((code) => !languages.installed.includes(code));
  return (
    <div className="ocr-languages">
      <h3 className="title-medium">OCR languages</h3>
      <ul className="chip-list" aria-label="OCR languages">
        {languages.installed.map((code) => (
          <li key={code} className="chip-row">
            <span className="body-medium">{code}</span>
            {languages.bundled.includes(code) ? (
              <span className="body-small on-surface-variant">built in</span>
            ) : (
              <IconButton
                icon="close"
                label={`Remove ${code}`}
                disabled={state.phase === "working"}
                onClick={() => void change({ command: "addon_remove_language", language: code })}
              />
            )}
          </li>
        ))}
      </ul>
      <div className="settings-field">
        <Select
          label="Add a language"
          value={choice}
          options={[{ value: "", label: "Choose a Tesseract language code" }, ...addable.map((code) => ({ value: code, label: code }))]}
          onChange={setChoice}
        />
        <Button
          variant="text"
          icon="download"
          disabled={!choice || state.phase === "working"}
          onClick={() => void change({ command: "addon_add_languages", languages: [choice] })}
        >
          {state.phase === "working" ? "Downloading…" : "Download"}
        </Button>
      </div>
      <p className="body-small on-surface-variant">Each language is a small file (1–15 MB) from the Tesseract project, checked against its pinned checksum.</p>
      {state.phase === "failed" ? (
        <p className="body-medium audio-problem" role="alert">
          {state.message}
        </p>
      ) : null}
    </div>
  );
}
