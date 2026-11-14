"""Screenshot the review page: as opened, with chapter 1 retitled, and after saving.

Usage:
    shoot_review.py URL OUT_DIR [CHROMIUM_EXECUTABLE]

Without CHROMIUM_EXECUTABLE, Playwright's own Chromium is used
(``playwright install chromium``). Note that clicking Save really saves the
reviewed chapters in the workspace being served.
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright


def main(url: str, out_dir: str, chromium: str | None) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1100, "height": 720})
        page.goto(url)
        page.wait_for_selector("article")
        page.screenshot(path=f"{out_dir}/review-1-open.png")

        first = page.locator("article").first
        title = first.locator("[name=title]")
        title.fill("Title Page")
        title.evaluate("e => e.style.outline = '3px solid #e8590c'")
        first.screenshot(path=f"{out_dir}/review-2-edit-title.png")
        title.evaluate("e => e.style.outline = ''")

        page.click("#save")
        # The page's CSP forbids eval, so wait with a selector, not a JS predicate.
        page.wait_for_selector("#status:not(:empty)")
        status = page.locator("#status").text_content() or ""
        if not status.startswith("Saved"):
            raise SystemExit(f"review save failed: {status}")
        page.locator("#save").scroll_into_view_if_needed()
        last = page.locator("article").last.bounding_box()
        save = page.locator("#save").bounding_box()
        assert last is not None and save is not None
        top = last["y"] + last["height"] - 160
        bottom = save["y"] + save["height"] + 30
        page.screenshot(
            path=f"{out_dir}/review-3-saved.png",
            clip={"x": 0, "y": top, "width": 1100, "height": bottom - top},
        )
        browser.close()
        print("review-1-open.png, review-2-edit-title.png, review-3-saved.png:", status)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
