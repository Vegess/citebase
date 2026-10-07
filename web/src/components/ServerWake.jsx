import { useEffect, useState } from "react";
import { wakeServer } from "../lib/api";

/**
 * Starts waking the API the moment the site loads, and tells the visitor
 * what is happening if it takes more than a couple of seconds.
 */
export function ServerWake() {
  const [state, setState] = useState("checking"); // checking | slow | ready | down

  useEffect(() => {
    let done = false;
    const slowTimer = setTimeout(() => {
      if (!done) setState("slow");
    }, 2500);
    wakeServer().then((ok) => {
      done = true;
      clearTimeout(slowTimer);
      setState(ok ? "ready" : "down");
    });
    return () => {
      done = true;
      clearTimeout(slowTimer);
    };
  }, []);

  if (state !== "slow" && state !== "down") return null;
  return (
    <div
      role="status"
      className={`sticky top-0 z-50 border-b px-5 py-2 text-center text-sm ${
        state === "down" ? "border-danger/25 bg-danger-soft text-danger" : "border-warn/25 bg-warn-soft text-warn"
      }`}
    >
      {state === "slow" ? (
        <>
          <span className="pulse-soft mr-2 inline-block h-2 w-2 rounded-full bg-warn align-middle" />
          Starting the server — the free plan sleeps when idle, so the first visit takes up to a minute. You can keep
          reading or sign in meanwhile.
        </>
      ) : (
        "The server isn't responding. Please try again in a few minutes."
      )}
    </div>
  );
}
