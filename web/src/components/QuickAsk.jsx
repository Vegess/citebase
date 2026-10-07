import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/**
 * Floating "Ask" button on every signed-in page except Ask itself.
 * Sends the question to the chat page, which asks it in a new conversation.
 */
export function QuickAsk() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const inputRef = useRef(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (location.pathname.startsWith("/chat")) return null;

  function submit(e) {
    e.preventDefault();
    const asked = question.trim();
    if (!asked) return;
    setOpen(false);
    setQuestion("");
    navigate("/chat", { state: { ask: asked } });
  }

  return (
    <div className="fixed right-5 bottom-5 z-40 flex flex-col items-end gap-3">
      {open && (
        <form
          onSubmit={submit}
          className="w-[min(22rem,calc(100vw-2.5rem))] rounded-lg border border-rule bg-surface p-3 shadow-lg"
        >
          <label htmlFor="quick-ask" className="mb-2 block text-sm font-medium text-ink">
            Ask your documents
          </label>
          <div className="flex gap-2">
            <input
              id="quick-ask"
              ref={inputRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. How many leave days do I get?"
              className="min-w-0 flex-1 rounded-md border border-rule bg-paper px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-signal focus:outline-none"
            />
            <button type="submit" className="rounded-md bg-signal px-3 py-2 text-sm font-medium text-white">
              Ask
            </button>
          </div>
        </form>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? "Close quick ask" : "Quick ask"}
        className="flex h-14 w-14 items-center justify-center rounded-full bg-signal text-white shadow-lg transition-transform hover:scale-105"
      >
        {open ? (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
            <path d="M9 10h6M9 13.5h4" />
          </svg>
        )}
      </button>
    </div>
  );
}
