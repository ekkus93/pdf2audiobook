import { type RefObject, useEffect, useRef } from "react";

/** Listens for a DOM event on a custom element; React's own props don't reach Lit events. */
export function useElementEvent<E extends Event = Event>(
  ref: RefObject<HTMLElement | null>,
  name: string,
  handler: ((event: E) => void) | undefined,
): void {
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const listener = (event: Event) => latest.current?.(event as E);
    element.addEventListener(name, listener);
    return () => element.removeEventListener(name, listener);
  }, [ref, name]);
}
