import { useEffect, useState } from "react";
import { engineNoticeText, engineNotices, errorMessage } from "../engine/api";
import type { Notice } from "../engine/types";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

type Shown = { name: string; text: string } | { name: string; problem: string } | null;

/** The app's licence and every component inside its built-in engine (self-contained app spec C9). */
export function About() {
  const [notices, setNotices] = useState<Notice[] | null>(null);
  const [shown, setShown] = useState<Shown>(null);
  useEffect(() => {
    let current = true;
    engineNotices()
      .then((list) => current && setNotices(list))
      .catch(() => current && setNotices(null));
    return () => {
      current = false;
    };
  }, []);
  const show = async (index: number, name: string) => {
    try {
      setShown({ name, text: await engineNoticeText(index) });
    } catch (error) {
      setShown({ name, problem: errorMessage(error) });
    }
  };
  return (
    <div className="about">
      <p className="body-medium">pdf2audiobook is free software under the Apache License 2.0.</p>
      {notices && notices.length > 0 ? (
        <>
          <p className="body-medium on-surface-variant">
            Its built-in engine includes these {notices.length} components, unmodified, each under its own licence. They run as separate
            programs and data; where to get each one's source is listed with it.
          </p>
          <ul className="notice-list" aria-label="Components">
            {notices.map((notice, index) => (
              <li key={`${notice.name}-${index}`} className="notice-row">
                <div>
                  <div className="title-small">
                    {notice.name} {notice.version}
                  </div>
                  <p className="body-small on-surface-variant">{notice.license}</p>
                  <p className="body-small on-surface-variant notice-source">Source: {notice.source}</p>
                </div>
                <Button variant="text" icon="description" onClick={() => void show(index, notice.name)}>
                  Licence
                </Button>
              </li>
            ))}
          </ul>
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
