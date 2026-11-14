import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom lacks two browser features @material/web's form controls use. These test-only shims
// let the elements upgrade; the tests check the wrappers' behaviour, not the browser's.
const internals = globalThis.ElementInternals?.prototype as unknown as Record<string, unknown> | undefined;
if (internals && !("setFormValue" in internals)) {
  Object.assign(internals, {
    setFormValue() {},
    setValidity() {},
    checkValidity: () => true,
    reportValidity: () => true,
  });
}
if (!("IntersectionObserver" in globalThis)) {
  class NoopIntersectionObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }
  Object.assign(globalThis, { IntersectionObserver: NoopIntersectionObserver });
}

const dialog = globalThis.HTMLDialogElement?.prototype;
if (dialog && !dialog.showModal) {
  Object.assign(dialog, {
    showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
    close(this: HTMLDialogElement) {
      this.removeAttribute("open");
    },
  });
}

if (typeof Element !== "undefined" && !Element.prototype.animate) {
  Element.prototype.animate = function animate() {
    return {
      finished: Promise.resolve(),
      cancel() {},
      finish() {},
      addEventListener() {},
      removeEventListener() {},
    } as unknown as Animation;
  };
}

afterEach(() => {
  cleanup();
});
