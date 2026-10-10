import { useState } from "react";

const KEY = "citebase-beta-banner-dismissed";

function read() {
  try {
    return window.localStorage.getItem(KEY) === "true";
  } catch {
    return false; // storage blocked: just show the banner
  }
}

/** Dismissible beta notice on the Documents page. */
export function DemoBanner() {
  const [dismissed, setDismissed] = useState(read);
  if (dismissed) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(KEY, "true");
    } catch {
      /* fine: it comes back next visit */
    }
  };

  return (
    <div className="border-b border-warn/20 bg-warn-soft/30 px-5 py-2.5 text-sm text-warn">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
        <p>
          <span className="font-medium">Beta</span> — please don't upload highly confidential documents yet.
        </p>
        <button onClick={dismiss} className="ml-auto text-xs opacity-60 transition-opacity hover:opacity-100" aria-label="Dismiss notice">
          Dismiss
        </button>
      </div>
    </div>
  );
}
