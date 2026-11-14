import { useEffect, useState } from "react";
import { getSettings } from "./engine/api";
import { Library } from "./screens/Library";
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

  useEffect(() => {
    void getSettings()
      .then((settings) => {
        document.documentElement.dataset.theme = settings.theme;
      })
      .catch(() => undefined);
  }, []);

  return (
    <div className="app">
      <NavigationRail destinations={DESTINATIONS} current={page} onSelect={setPage} />
      <div className="app-main">
        <TopAppBar title={TITLES[page]} />
        <main className="app-content" aria-label={TITLES[page]}>
          {page === "library" ? <Library onOpenSettings={() => setPage("settings")} /> : null}
          {page === "settings" ? <Setup /> : null}
          {page === "run" ? (
            <div className="empty-state">
              <h2 className="headline-small">Nothing is running</h2>
              <p className="body-medium">Analysis and conversion progress will appear here.</p>
            </div>
          ) : null}
        </main>
      </div>
    </div>
  );
}
