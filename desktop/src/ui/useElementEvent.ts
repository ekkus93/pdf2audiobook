import { type RefObject, useLayoutEffect, useRef } from "react";

interface Attached {
  element: HTMLElement;
  name: string;
  listener: (event: Event) => void;
}

/**
 * Listens for a DOM event on a custom element; React's own props don't reach Lit events.
 * Layout effects attach the listener before the element can be painted, so no early event is lost.
 * The listener follows the element: a component that renders a different tag in place (a Button
 * changing variant) gets a new element, and the listener moves to it.
 */
export function useElementEvent<E extends Event = Event>(
  ref: RefObject<HTMLElement | null>,
  name: string,
  handler: ((event: E) => void) | undefined,
): void {
  const latest = useRef(handler);
  const attached = useRef<Attached | null>(null);
  useLayoutEffect(() => {
    latest.current = handler;
    const element = ref.current;
    const current = attached.current;
    if (current?.element === element && current?.name === name) return;
    current?.element.removeEventListener(current.name, current.listener);
    attached.current = null;
    if (!element) return;
    const listener = (event: Event) => latest.current?.(event as E);
    element.addEventListener(name, listener);
    attached.current = { element, name, listener };
  });
  useLayoutEffect(
    () => () => {
      const current = attached.current;
      current?.element.removeEventListener(current.name, current.listener);
      attached.current = null;
    },
    [],
  );
}
