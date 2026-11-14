import { describe, expect, it } from "vitest";
import type { InspectManifest, LibraryBook } from "../engine/types";
import { relativeTime, summarize } from "./bookState";

const INSPECT: InspectManifest = {
  title: "The Lighthouse at Gull Point",
  source_path: "/books/lighthouse.pdf",
  review_required: [],
  review_acknowledged: [],
  approved: false,
  chapters: [
    { number: 1, title: "One", confidence: 0.9, manually_approved: false },
    { number: 2, title: "Two", confidence: 0.82, manually_approved: false },
  ],
};

function book(changes: Partial<LibraryBook> = {}, inspect: Partial<InspectManifest> = {}): LibraryBook {
  return {
    workspace: "/out/lighthouse-2b79af3fb1",
    manifest: "/out/lighthouse-2b79af3fb1/manifest.json",
    analyzed: true,
    source: null,
    inspect: { ...INSPECT, ...inspect },
    error: null,
    run_status: null,
    thumbnail: null,
    ...changes,
  };
}

describe("summarize", () => {
  it("a book added but not analyzed is titled from its file", () => {
    const summary = summarize(book({ analyzed: false, source: "/books/My Book.epub", inspect: null }), 0.75);
    expect(summary).toEqual({ title: "My Book", state: "not_analyzed", chapters: null, converted: null, lastRun: null });
  });

  it("an analyzed book with confident chapters is ready", () => {
    expect(summarize(book(), 0.75)).toMatchObject({ title: INSPECT.title, state: "ready", chapters: 2 });
  });

  it("a low-confidence chapter needs review until approved", () => {
    const uncertain = { chapters: [{ number: 1, title: "One", confidence: 0.7, manually_approved: false }] };
    expect(summarize(book({}, uncertain), 0.75).state).toBe("needs_review");
    const approved = { chapters: [{ number: 1, title: "One", confidence: 0.7, manually_approved: true }] };
    expect(summarize(book({}, approved), 0.75).state).toBe("ready");
    expect(summarize(book({}, { ...uncertain, approved: true }), 0.75).state).toBe("ready");
  });

  it("an unacknowledged book-wide review reason needs review", () => {
    expect(summarize(book({}, { review_required: ["damaged_source"] }), 0.75).state).toBe("needs_review");
    const acknowledged = { review_required: ["damaged_source"], review_acknowledged: ["damaged_source"] };
    expect(summarize(book({}, acknowledged), 0.75).state).toBe("ready");
  });

  it("counts converted chapters and recognises a finished book", () => {
    const partial = { conversion_status: { chapters: [{ number: 1, status: "complete" }, { number: 2, status: "pending" }] } };
    expect(summarize(book({}, partial), 0.75)).toMatchObject({ state: "ready", converted: 1 });
    const done = { conversion_status: { chapters: [{ number: 1, status: "complete" }, { number: 2, status: "complete" }] } };
    expect(summarize(book({}, done), 0.75)).toMatchObject({ state: "converted", converted: 2 });
    const failed = { conversion_status: { chapters: [{ number: 1, status: "failed" }] } };
    expect(summarize(book({}, failed), 0.75).state).toBe("failed");
  });

  it("a running analyze or convert shows as in progress, with its last report time", () => {
    const running = (command: string) =>
      book({ run_status: { command, state: "running", updated_at: "2026-11-14T10:00:00+00:00", elapsed_seconds: 5 } });
    expect(summarize(running("convert"), 0.75)).toMatchObject({ state: "converting", lastRun: "2026-11-14T10:00:00+00:00" });
    expect(summarize(running("analyze"), 0.75).state).toBe("analyzing");
  });

  it("a workspace that can't be inspected needs attention", () => {
    expect(summarize(book({ inspect: null, error: "Cannot read" }), 0.75)).toMatchObject({
      state: "failed",
      title: "lighthouse-2b79af3fb1",
    });
  });
});

describe("relativeTime", () => {
  const now = new Date("2026-11-14T12:00:00Z");
  it.each([
    ["2026-11-14T11:59:40Z", "this minute"],
    ["2026-11-14T11:55:00Z", "5 minutes ago"],
    ["2026-11-14T09:00:00Z", "3 hours ago"],
    ["2026-11-13T12:00:00Z", "yesterday"],
    ["2026-10-01T12:00:00Z", "last month"],
  ])("%s is %s", (iso, expected) => {
    expect(relativeTime(iso, now)).toBe(expected);
  });
});
