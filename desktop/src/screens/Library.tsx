import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useState } from "react";
import { addBook, errorMessage, library } from "../engine/api";
import type { BridgeError, Library as LibraryData, LibraryBook } from "../engine/types";
import { Button } from "../ui/Button";
import { Fab } from "../ui/Fab";
import { Icon } from "../ui/Icon";
import { CircularProgress } from "../ui/Progress";
import { Snackbar } from "../ui/Snackbar";
import type { IconName } from "../theme/icons.generated";
import { relativeTime, summarize, type BookState } from "./bookState";
import "./screens.css";
import "./library.css";

type State =
  | { phase: "loading" }
  | { phase: "no-engine"; message: string }
  | { phase: "failed"; message: string }
  | { phase: "ready"; data: LibraryData };

/** Loads the library; never rejects. */
export async function loadLibrary(): Promise<State> {
  try {
    return { phase: "ready", data: await library() };
  } catch (error) {
    const bridge = error as BridgeError;
    if (bridge && typeof bridge === "object" && bridge.kind === "locate") {
      return { phase: "no-engine", message: bridge.message };
    }
    return { phase: "failed", message: errorMessage(error) };
  }
}

const STATES: Record<BookState, { label: string; icon: IconName; tone: "primary" | "tertiary" | "error" | "neutral" }> = {
  not_analyzed: { label: "Not analyzed", icon: "hourglass_top", tone: "neutral" },
  needs_review: { label: "Needs review", icon: "rate_review", tone: "tertiary" },
  ready: { label: "Ready to convert", icon: "task_alt", tone: "primary" },
  analyzing: { label: "Analyzing", icon: "sync", tone: "primary" },
  converting: { label: "Converting", icon: "graphic_eq", tone: "primary" },
  converted: { label: "Converted", icon: "headphones", tone: "primary" },
  failed: { label: "Needs attention", icon: "error", tone: "error" },
};

/** Library (spec D4.2): the books in the output folder, and adding a new one. */
interface LibraryProps {
  onOpenSettings?: () => void;
  /** Opens a book's page. */
  onOpenBook?: (book: LibraryBook, library: LibraryData) => void;
}

export function Library({ onOpenSettings, onOpenBook }: LibraryProps) {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    void loadLibrary().then((next) => current && setState(next));
    return () => {
      current = false;
    };
  }, [attempt]);

  const add = async () => {
    const picked = await open({
      multiple: false,
      directory: false,
      filters: [{ name: "Books", extensions: ["pdf", "epub"] }],
    });
    if (typeof picked !== "string") return;
    try {
      await addBook(picked);
      setMessage(`Added ${picked.split(/[\\/]/).pop()}`);
      setAttempt((value) => value + 1);
    } catch (error) {
      setMessage(errorMessage(error));
    }
  };

  return (
    <div className="screen library">
      {state.phase === "loading" ? (
        <div className="screen-loading">
          <CircularProgress label="Loading your books" />
          <span className="body-medium on-surface-variant">Loading your books…</span>
        </div>
      ) : null}
      {state.phase === "no-engine" ? (
        <div className="empty-state">
          <Icon name="terminal" size={48} />
          <h2 className="headline-small">pdf2audiobook isn't set up yet</h2>
          <p className="body-medium on-surface-variant">{state.message}</p>
          <Button variant="tonal" icon="settings" onClick={onOpenSettings}>
            Open setup
          </Button>
        </div>
      ) : null}
      {state.phase === "failed" ? (
        <div className="empty-state">
          <Icon name="error" size={48} />
          <h2 className="headline-small">Your books couldn't be loaded</h2>
          <p className="body-medium on-surface-variant">{state.message}</p>
          <Button variant="tonal" icon="refresh" onClick={() => setAttempt((value) => value + 1)}>
            Try again
          </Button>
        </div>
      ) : null}
      {state.phase === "ready" && state.data.books.length === 0 ? (
        <div className="empty-state">
          <span className="empty-art" aria-hidden="true">
            <Icon name="auto_stories" size={56} />
          </span>
          <h2 className="headline-small">No books yet</h2>
          <p className="body-medium on-surface-variant">
            Add a PDF or EPUB to turn it into an audiobook. Books are kept in {state.data.output_dir}.
          </p>
        </div>
      ) : null}
      {state.phase === "ready" && state.data.books.length > 0 ? (
        <ul className="book-grid" aria-label="Books">
          {state.data.books.map((book) => (
            <BookCard
              key={book.workspace}
              book={book}
              minConfidence={state.data.min_boundary_confidence}
              onOpen={onOpenBook ? () => onOpenBook(book, state.data) : undefined}
            />
          ))}
        </ul>
      ) : null}
      {state.phase === "ready" && state.data.commands.length > 0 ? (
        <details className="details">
          <summary>Details</summary>
          <p className="body-medium on-surface-variant">Commands this screen ran:</p>
          {state.data.commands.map((command) => (
            <pre key={command} className="command">
              {command}
            </pre>
          ))}
        </details>
      ) : null}
      {state.phase === "ready" ? (
        <div className="fab-anchor">
          <Fab icon="add" label="Add book" onClick={() => void add()} />
        </div>
      ) : null}
      <Snackbar message={message} />
    </div>
  );
}

function BookCard({ book, minConfidence, onOpen }: { book: LibraryBook; minConfidence: number; onOpen?: () => void }) {
  const summary = summarize(book, minConfidence);
  const status = STATES[summary.state];
  const facts = [
    summary.chapters !== null ? `${summary.chapters} chapters` : null,
    summary.converted !== null && summary.chapters !== null && summary.converted < summary.chapters
      ? `${summary.converted} converted`
      : null,
  ].filter(Boolean);
  return (
    <li className="book-card" aria-label={summary.title}>
      {onOpen ? (
        <button type="button" className="book-open" aria-label={`Open ${summary.title}`} onClick={onOpen}>
          <md-ripple />
        </button>
      ) : null}
      <div className="book-cover">
        {book.thumbnail ? (
          <img src={book.thumbnail} alt="" />
        ) : (
          <span className="book-cover-fallback" aria-hidden="true">
            <Icon name="menu_book" size={40} />
          </span>
        )}
      </div>
      <div className="book-body">
        <h3 className="book-title">{summary.title}</h3>
        <span className={`status-chip tone-${status.tone}`}>
          <Icon name={status.icon} filled size={16} />
          {status.label}
        </span>
        <div className="book-meta body-medium on-surface-variant">
          {facts.length ? <span>{facts.join(" · ")}</span> : null}
          {summary.lastRun ? <span>Last run {relativeTime(summary.lastRun)}</span> : null}
          {book.error ? <span className="book-error">{book.error}</span> : null}
        </div>
      </div>
    </li>
  );
}
