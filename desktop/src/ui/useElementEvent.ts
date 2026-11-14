import { type RefObject, useLayoutEffect, useRef } from "react";

/**
 * Listens for a DOM event on a custom element; React's own props don't reach Lit events.
 * Layout effects attach the listener before the element can be painted, so no early event is lost.
 */
export function useElementEvent<E extends Event = Event>(
  ref: RefObject<HTMLElement | null>,
  name: string,
  handler: ((event: E) => void) | undefined,
): void {
  const latest = useRef(handler);
  useLayoutEffect(() => {
    latest.current = handler;
  });
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const listener = (event: Event) => latest.current?.(event as E);
    element.addEventListener(name, listener);
    return () => element.removeEventListener(name, listener);
  }, [ref, name]);
}
