import { createContext, useCallback, useContext, useState } from "react";
import { Icon } from "./icons";

/* ---------------- Button ---------------- */

const variants = {
  primary:
    "bg-signal text-white hover:bg-[#2449d6] disabled:bg-rule disabled:text-muted",
  secondary:
    "bg-surface text-ink border border-rule hover:border-ink-soft disabled:text-muted",
  ghost: "text-ink-soft hover:text-ink hover:bg-rule-soft",
  danger: "text-danger hover:bg-danger-soft",
};

export function Button({ variant = "primary", className = "", size, ...props }) {
  const sizeClasses = size === "sm" ? "px-3 py-1.5 text-xs" : "px-4 py-2 text-sm";
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:cursor-not-allowed ${sizeClasses} ${variants[variant]} ${className}`}
      {...props}
    />
  );
}

/* ---------------- Field ---------------- */

export function Field({ label, hint, ...props }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>
      <input
        className="w-full rounded-md border border-rule bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-signal focus:outline-none"
        {...props}
      />
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

/* ---------------- Password input ---------------- */

/** Password field with a show/hide toggle. Takes the same props as Field. */
export function PasswordInput({ label, hint, className = "py-2", ...props }) {
  const [visible, setVisible] = useState(false);
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>
      <span className="relative block">
        <input
          className={`w-full rounded-md border border-rule bg-surface px-3 pr-10 text-sm text-ink placeholder:text-muted focus:border-signal focus:outline-none ${className}`}
          {...props}
          type={visible ? "text" : "password"}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-muted hover:text-ink focus-visible:text-ink"
        >
          {visible ? <Icon.EyeOff width={18} height={18} /> : <Icon.Eye width={18} height={18} />}
        </button>
      </span>
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

/* ---------------- Status badge ---------------- */

const statusStyles = {
  ready: "bg-source-soft text-source",
  queued: "bg-warn-soft text-warn",
  chunking: "bg-warn-soft text-warn",
  embedding: "bg-warn-soft text-warn",
  failed: "bg-danger-soft text-danger",
  superseded: "bg-rule-soft text-muted",
  reupload_required: "bg-danger-soft text-danger",
};

const statusLabels = {
  queued: "queued",
  chunking: "reading",
  embedding: "indexing",
  ready: "ready",
  failed: "failed",
  reupload_required: "re-upload needed",
  superseded: "older version",
};

/** Statuses the backend is still working through; the UI polls these. */
export const IN_PROGRESS = new Set(["queued", "chunking", "embedding"]);

export function StatusBadge({ status }) {
  const style = statusStyles[status] ?? "bg-rule-soft text-muted";
  return (
    <span
      className={`inline-flex items-center rounded-sm px-1.5 py-0.5 font-mono text-[11px] tracking-tight ${style} ${
        IN_PROGRESS.has(status) ? "pulse-soft" : ""
      }`}
    >
      {statusLabels[status] ?? status}
    </span>
  );
}

/* ---------------- Empty state ---------------- */

export function EmptyState({ title, children }) {
  return (
    <div className="rounded-lg border border-dashed border-rule bg-surface/60 px-6 py-12 text-center">
      <p className="font-display text-lg text-ink">{title}</p>
      <p className="mx-auto mt-1 max-w-sm text-sm text-muted">{children}</p>
    </div>
  );
}

/* ---------------- Toasts ---------------- */

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const notify = useCallback((message, tone = "error") => {
    const id = crypto.randomUUID();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto max-w-sm rounded-md border px-4 py-2.5 text-sm shadow-sm ${
              t.tone === "error"
                ? "border-danger/25 bg-danger-soft text-danger"
                : "border-source/25 bg-source-soft text-source"
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

/** Shown instead of an endless loading placeholder when a page fails to load. */
export function LoadError({ onRetry, children = "This page couldn't load." }) {
  return (
    <div className="rounded-xl border border-rule bg-surface px-6 py-10 text-center">
      <p className="text-sm text-ink">{children}</p>
      <p className="mt-1 text-xs text-muted">The server may be waking up. Give it a moment.</p>
      <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
