import { useEffect, useState } from "react";
import { getSettings } from "./engine/api";
import { BookPage } from "./screens/BookPage";
import { Library } from "./screens/Library";
import type { Library as LibraryData, LibraryBook, Request } from "./engine/types";
import { Setup } from "./screens/Setup";
import { NavigationRail, type Destination } from "./ui/NavigationRail";
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
  const [started, setStarted] = useState<{ request: Request; workspace: string } | null>(null);

  const select = (next: Page) => {
    setOpen(null);
    setPage(next);
  };

  useEffect(() => {
    void getSettings()
      .then((settings) => {
        document.documentElement.dataset.theme = settings.theme;
      })
      .catch(() => undefined);
  }, []);

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
              onStart={(request, workspace) => {
                setStarted({ request, workspace });
                setPage("run");
              }}
            />
          ) : null}
          {page === "library" && !open ? (
            <Library onOpenSettings={() => select("settings")} onOpenBook={(book, library) => setOpen({ book, library })} />
          ) : null}
          {page === "settings" ? <Setup /> : null}
          {page === "run" ? (
            <div className="empty-state">
              <h2 className="headline-small">{started ? "Starting…" : "Nothing is running"}</h2>
              <p className="body-medium">Analysis and conversion progress will appear here.</p>
            </div>
          ) : null}
        </main>
      </div>
    </div>
  );
}
