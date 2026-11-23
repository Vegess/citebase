import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/*
 * Motion primitives. Everything here honours prefers-reduced-motion: with it on,
 * elements render in their final state immediately, nothing loops, and route
 * changes switch instantly. index.css carries the matching media query for the
 * CSS-only animations.
 */

const QUERY = "(prefers-reduced-motion: reduce)";

/** Non-hook read, for code that runs outside render (router, event handlers). */
export function prefersReducedMotion() {
  return typeof window !== "undefined" && Boolean(window.matchMedia?.(QUERY).matches);
}

function subscribe(onChange) {
  const mq = typeof window !== "undefined" ? window.matchMedia?.(QUERY) : null;
  if (!mq) return () => {};
  mq.addEventListener?.("change", onChange);
  return () => mq.removeEventListener?.("change", onChange);
}

/** Live value of prefers-reduced-motion; re-renders when the setting flips. */
export function usePrefersReducedMotion() {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false);
}

/**
 * Tracks whether an element is on screen. `once` stops observing after the
 * first intersection (used by reveals); otherwise it keeps reporting (used to
 * pause loops off-screen). Without IntersectionObserver it reports visible.
 */
export function useInView({ once = false, rootMargin = "0px", threshold = 0 } = {}) {
  const [inView, setInView] = useState(false);
  const observer = useRef(null);

  const ref = useCallback(
    (node) => {
      observer.current?.disconnect();
      observer.current = null;
      if (!node) return;
      if (typeof IntersectionObserver === "undefined") {
        setInView(true);
        return;
      }
      const io = new IntersectionObserver(
        ([entry]) => {
          setInView(entry.isIntersecting);
          if (entry.isIntersecting && once) io.disconnect();
        },
        { rootMargin, threshold },
      );
      io.observe(node);
      observer.current = io;
    },
    [once, rootMargin, threshold],
  );

  useEffect(() => () => observer.current?.disconnect(), []);
  return [ref, inView];
}

/**
 * Fade/rise-in once per element. Returns a callback ref; the element gets the
 * `reveal` class from the caller and `is-revealed` once it scrolls into view.
 */
export function useReveal() {
  const reduced = usePrefersReducedMotion();
  const [ref, inView] = useInView({ once: true, rootMargin: "0px 0px -10% 0px" });
  const node = useRef(null);
  const shown = reduced || inView;

  const setRef = useCallback(
    (el) => {
      node.current = el;
      ref(el);
    },
    [ref],
  );

  useEffect(() => {
    if (shown) node.current?.classList.add("is-revealed");
  }, [shown]);

  return setRef;
}

const easeOutCubic = (t) => 1 - (1 - t) ** 3;

/** Animates a number from 0 to `target` with requestAnimationFrame. */
export function useCountUp(target, { duration = 900, start = true } = {}) {
  const reduced = usePrefersReducedMotion();
  const [value, setValue] = useState(reduced ? target : 0);

  useEffect(() => {
    if (reduced || !start || typeof requestAnimationFrame === "undefined") {
      setValue(target);
      return undefined;
    }
    let frame;
    const t0 = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - t0) / duration);
      setValue(Math.round(target * easeOutCubic(t)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, duration, start, reduced]);

  return value;
}
