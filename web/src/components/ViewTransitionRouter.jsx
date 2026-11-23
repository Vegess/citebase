import { useLayoutEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { createPath, parsePath, Router } from "react-router-dom";
import { prefersReducedMotion } from "../hooks/motion";

/*
 * A drop-in for <BrowserRouter> that commits each page change inside
 * document.startViewTransition, so the browser cross-fades old and new pages.
 * flushSync makes React render the new route synchronously inside the
 * transition callback, which is what lets the browser snapshot the new state.
 * Where the API is missing, or the user prefers reduced motion, the switch is
 * instant. Same history.state shape as BrowserRouter ({usr, key, idx}).
 */

const createKey = () => Math.random().toString(36).slice(2, 10);

function readLocation() {
  const { pathname, search, hash } = window.location;
  const st = window.history.state || {};
  return { pathname, search, hash, state: st.usr ?? null, key: st.key || "default" };
}

function withTransition(update, samePage) {
  if (samePage || typeof document.startViewTransition !== "function" || prefersReducedMotion()) {
    update();
    return;
  }
  document.startViewTransition(() => flushSync(update));
}

export function ViewTransitionRouter({ children }) {
  const [nav, setNav] = useState(() => ({ action: "POP", location: readLocation() }));
  const current = useRef(nav.location);
  current.current = nav.location;

  const navigator = useRef(null);
  if (!navigator.current) {
    const idx = () => window.history.state?.idx ?? 0;
    const go = (action, to, state) => {
      const target = typeof to === "string" ? parsePath(to) : to;
      const key = createKey();
      const entry = { usr: state ?? null, key, idx: action === "PUSH" ? idx() + 1 : idx() };
      const url = createPath({ pathname: current.current.pathname, ...target });
      if (action === "PUSH") window.history.pushState(entry, "", url);
      else window.history.replaceState(entry, "", url);
      const location = readLocation();
      withTransition(
        () => setNav({ action, location }),
        location.pathname === current.current.pathname,
      );
    };
    navigator.current = {
      createHref: (to) => (typeof to === "string" ? to : createPath(to)),
      encodeLocation: (to) => {
        const url = new URL(typeof to === "string" ? to : createPath(to), window.location.origin);
        return { pathname: url.pathname, search: url.search, hash: url.hash };
      },
      push: (to, state) => go("PUSH", to, state),
      replace: (to, state) => go("REPLACE", to, state),
      go: (delta) => window.history.go(delta),
    };
  }

  useLayoutEffect(() => {
    if (!window.history.state?.key) {
      window.history.replaceState({ usr: null, key: "default", idx: 0 }, "");
    }
    const onPop = () => {
      const location = readLocation();
      withTransition(() => setNav({ action: "POP", location }), location.pathname === current.current.pathname);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  return (
    <Router location={nav.location} navigationType={nav.action} navigator={navigator.current}>
      {children}
    </Router>
  );
}
