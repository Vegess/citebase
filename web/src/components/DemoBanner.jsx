import { useState } from "react";

/**
 * Dismissible banner shown on Demo/Documents and Chat pages.
 * Informs users that this is a demo environment with data ephemera.
 */
export function DemoBanner() {
  const [dismissed, setDismissed] = useState(() => {
    // Persist dismissal in localStorage for the session
    const stored = localStorage.getItem("demo-banner-dismissed");
    return stored === "true";
  });

  if (dismissed) return null;

  const handleDismiss = () => {
    setDismissed(true);
    localStorage.setItem("demo-banner-dismissed", "true");
  };

  return (
    <div className="border-b border-warn/20 bg-warn-soft/30 px-5 py-2.5 text-sm text-warn">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
        <p>
          <span className="font-medium">Demo project</span> — please don't upload
          confidential documents. Data may be reset at any time.
        </p>
        <button
          onClick={handleDismiss}
          className="ml-auto text-xs opacity-60 hover:opacity-100 transition-opacity"
          aria-label="Dismiss"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
