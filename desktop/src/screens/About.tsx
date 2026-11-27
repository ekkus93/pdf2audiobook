import { useEffect, useState } from "react";
import { appNoticeText, appNotices, engineNoticeText, engineNotices, errorMessage } from "../engine/api";
import type { Notice } from "../engine/types";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

type Shown = { name: string; text: string } | { name: string; problem: string } | null;

function useNotices(load: () => Promise<Notice[] | null>): Notice[] | null {
  const [notices, setNotices] = useState<Notice[] | null>(null);
  useEffect(() => {
    let current = true;
    load()
      .then((list) => current && setNotices(list))
      .catch(() => current && setNotices(null));
    return () => {
      current = false;
    };
  }, [load]);
  return notices;
}

function NoticeList({
  label,
  notices,
  first = 0,
  onShow,
}: {
  label: string;
  notices: Notice[];
  first?: number;
  onShow: (index: number, name: string) => void;
}) {
  return (
    <ul className="notice-list" aria-label={label}>
      {notices.slice(first).map((notice, offset) => (
        <li key={`${notice.name}-${notice.version}-${offset}`} className="notice-row">
          <div>
            <div className="title-small">
              {notice.name} {notice.version}
            </div>
            <p className="body-small on-surface-variant">{notice.license}</p>
            <p className="body-small on-surface-variant notice-source">Source: {notice.source}</p>
          </div>
          <Button variant="text" icon="description" onClick={() => onShow(first + offset, notice.name)}>
            Licence
          </Button>
        </li>
      ))}
    </ul>
  );
}

/**
 * The app's licences (self-contained app spec C9). An installed app combines its Apache-2.0
 * code with AGPL-3.0 and GPL components in the built-in engine, so as distributed it is under
 * the GNU AGPL 3.0; the packaged app lists its own crates and npm packages and the engine's
 * components. A development build has neither list.
 */
export function About() {
  const app = useNotices(appNotices);
  const engine = useNotices(engineNotices);
  const [shown, setShown] = useState<Shown>(null);
  const show = (read: (index: number) => Promise<string>) => async (index: number, name: string) => {
    try {
      setShown({ name, text: await read(index) });
    } catch (error) {
      setShown({ name, problem: errorMessage(error) });
    }
  };
  const showApp = show(appNoticeText);
  const showEngine = show(engineNoticeText);
  const packaged = app !== null && app.length > 0;
  return (
    <div className="about">
      <p className="body-medium">pdf2audiobook's own source code is free software under the Apache License 2.0.</p>
      {packaged ? (
        <>
          <p className="body-medium">
            This installed app also includes its built-in engine, with PyMuPDF (GNU AGPL 3.0) and components under the GNU GPL,
            so the app as distributed is under the GNU Affero General Public License 3.0. The complete source of this build, its
            copyleft components included, is published next to its installers.
          </p>
          <div className="about-actions">
            <Button variant="text" icon="description" onClick={() => void showApp(0, app[0].name)}>
              GNU AGPL 3.0 and Apache 2.0
            </Button>
          </div>
          {app.length > 1 ? (
            <details className="notice-group">
              <summary className="title-small">The app's {app.length - 1} libraries</summary>
              <NoticeList label="App libraries" notices={app} first={1} onShow={(index, name) => void showApp(index, name)} />
            </details>
          ) : null}
        </>
      ) : null}
      {engine && engine.length > 0 ? (
        <>
          <p className="body-medium on-surface-variant">
            Its built-in engine includes these {engine.length} components, unmodified, each under its own licence; where to get
            each one's source is listed with it.
          </p>
          <NoticeList label="Components" notices={engine} onShow={(index, name) => void showEngine(index, name)} />
        </>
      ) : null}
      {shown ? (
        <Dialog
          open
          headline={`${shown.name} licence`}
          onClose={() => setShown(null)}
          actions={
            <Button variant="text" onClick={() => setShown(null)}>
              Close
            </Button>
          }
        >
          {"text" in shown ? (
            <pre className="notice-text">{shown.text}</pre>
          ) : (
            <p className="body-medium audio-problem" role="alert">
              {shown.problem}
            </p>
          )}
        </Dialog>
      ) : null}
    </div>
  );
}
