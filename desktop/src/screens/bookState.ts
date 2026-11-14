import type { LibraryBook } from "../engine/types";

export type BookState = "not_analyzed" | "needs_review" | "ready" | "analyzing" | "converting" | "converted" | "failed";

export interface BookSummary {
  title: string;
  state: BookState;
  chapters: number | null;
  /** Converted chapters, when conversion has started. */
  converted: number | null;
  /** When the last analyze or convert run last reported, as an ISO time. */
  lastRun: string | null;
}

function fileTitle(path: string): string {
  const name = path.split(/[\\/]/).pop() ?? path;
  return name.replace(/\.(pdf|epub)$/i, "");
}

/** What the Library shows for a book (spec D4.2). */
export function summarize(book: LibraryBook, minConfidence: number): BookSummary {
  const lastRun = book.run_status?.updated_at ?? null;
  if (!book.analyzed) {
    return { title: fileTitle(book.source ?? book.workspace), state: "not_analyzed", chapters: null, converted: null, lastRun: null };
  }
  const inspect = book.inspect;
  if (!inspect) {
    return { title: fileTitle(book.workspace), state: "failed", chapters: null, converted: null, lastRun };
  }
  const chapters = inspect.chapters.length;
  const statuses = inspect.conversion_status?.chapters ?? [];
  const converted = statuses.length ? statuses.filter((chapter) => chapter.status === "complete").length : null;
  const base = { title: inspect.title, chapters, converted, lastRun };
  if (book.run_status?.state === "running") {
    return { ...base, state: book.run_status.command === "convert" ? "converting" : "analyzing" };
  }
  if (statuses.some((chapter) => chapter.status === "failed")) {
    return { ...base, state: "failed" };
  }
  const unacknowledged = inspect.review_required.filter((code) => !inspect.review_acknowledged.includes(code));
  const uncertain = inspect.chapters.some((chapter) => chapter.confidence < minConfidence && !chapter.manually_approved);
  if (!inspect.approved && (unacknowledged.length > 0 || uncertain)) {
    return { ...base, state: "needs_review" };
  }
  if (converted !== null && converted === chapters) {
    return { ...base, state: "converted" };
  }
  return { ...base, state: "ready" };
}

/** "5 minutes ago", "2 days ago"; `now` is injectable for tests. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const seconds = Math.round((new Date(iso).getTime() - now.getTime()) / 1000);
  const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const steps: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["week", 604_800],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return format.format(0, "minute");
}
