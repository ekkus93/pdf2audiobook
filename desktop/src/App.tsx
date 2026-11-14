import { useState } from "react";
import { NavigationRail, type Destination } from "./ui/NavigationRail";
import { TopAppBar } from "./ui/TopAppBar";
import "./app.css";

type Page = "library" | "run" | "settings";

const DESTINATIONS: ReadonlyArray<Destination<Page>> = [
  { id: "library", label: "Library", icon: "library_books" },
  { id: "run", label: "Run", icon: "graphic_eq" },
  { id: "settings", label: "Settings", icon: "settings" },
];

const TITLES: Record<Page, string> = { library: "Library", run: "Run", settings: "Settings" };

export default function App() {
  const [page, setPage] = useState<Page>("library");
  return (
    <div className="app">
      <NavigationRail destinations={DESTINATIONS} current={page} onSelect={setPage} />
      <div className="app-main">
        <TopAppBar title={TITLES[page]} />
        <main className="app-content" aria-label={TITLES[page]} />
      </div>
    </div>
  );
}
