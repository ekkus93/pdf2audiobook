import { useEffect, useState } from "react";
import { errorMessage, getSettings, onCloseRequested, quitApp, startRun } from "./engine/api";
import type { Library as LibraryData, LibraryBook, Request } from "./engine/types";
import { BookPage } from "./screens/BookPage";
import { summarize } from "./screens/bookState";
import { Library } from "./screens/Library";
import { Run, type ActiveRun } from "./screens/Run";
import { Setup } from "./screens/Setup";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { NavigationRail, type Destination } from "./ui/NavigationRail";
import { Snackbar } from "./ui/Snackbar";
import { TopAppBar } from "./ui/TopAppBar";
import "./app.css";

type Page = "library" | "run" | "settings";

const DESTINATIONS: ReadonlyArray<Destination<Page>> = [
  { id: "library", label: "Library", icon: "library_books" },
  { id: "run", label: "Run", icon: "graphic_eq" },
  { id: "settings", label: "Settings", icon: "settings" },
];

const TITLES: Record<Page, string> = { library: "Library", run: "Run", settings: "Setup" };

export default function App() {
  const [page, setPage] = useState<Page>("library");
  const [open, setOpen] = useState<{ book: LibraryBook; library: LibraryData } | null>(null);
  const [run, setRun] = useState<ActiveRun | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmQuit, setConfirmQuit] = useState(false);
  const [quitting, setQuitting] = useState(false);

  useEffect(() => {
    void getSettings()
      .then((settings) => {
        document.documentElement.dataset.theme = settings.theme;
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let unsubscribe: (() => void) | undefined;
    void onCloseRequested(() => setConfirmQuit(true))
      .then((stop) => {
        unsubscribe = stop;
      })
      .catch(() => undefined);
    return () => unsubscribe?.();
  }, []);

  const select = (next: Page) => {
    if (next === "library") setOpen(null);
    setPage(next);
  };

  const start = async (request: Request, workspace: string) => {
    if (request.command !== "analyze" && request.command !== "convert") return;
    const title = open ? summarize(open.book, open.library.min_boundary_confidence).title : "Book";
    try {
      const id = await startRun(request, workspace);
      setRun({ id, title, command: request.command });
      setPage("run");
    } catch (error) {
      setMessage(errorMessage(error));
    }
  };

  const quit = async () => {
    setQuitting(true);
    await quitApp().catch(() => setQuitting(false));
  };

  return (
    <div className="app">
      <NavigationRail destinations={DESTINATIONS} current={page} onSelect={select} />
      <div className="app-main">
        <TopAppBar title={TITLES[page]} />
        <main className="app-content" aria-label={TITLES[page]}>
          {page === "library" && open ? (
            <BookPage
              book={open.book}
              outputDir={open.library.output_dir}
              minConfidence={open.library.min_boundary_confidence}
              onBack={() => setOpen(null)}
              onStart={(request, workspace) => void start(request, workspace)}
            />
          ) : null}
          {page === "library" && !open ? (
            <Library onOpenSettings={() => select("settings")} onOpenBook={(book, library) => setOpen({ book, library })} />
          ) : null}
          {page === "settings" ? <Setup /> : null}
          {page === "run" ? <Run run={run} onDone={open ? () => setPage("library") : undefined} /> : null}
        </main>
      </div>
      <Dialog
        open={confirmQuit}
        headline="Stop the running task and quit?"
        onClose={() => setConfirmQuit(false)}
        actions={
          <>
            <Button variant="text" onClick={() => setConfirmQuit(false)}>
              Keep running
            </Button>
            <Button icon="stop" onClick={() => void quit()} disabled={quitting}>
              {quitting ? "Stopping…" : "Stop and quit"}
            </Button>
          </>
        }
      >
        The task stops the same way as pressing Stop. Finished chapters are kept, and running it
        again continues where it left off.
      </Dialog>
      <Snackbar message={message} />
    </div>
  );
}
