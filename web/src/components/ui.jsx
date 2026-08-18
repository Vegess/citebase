import { createContext, useCallback, useContext, useState } from "react";

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

/* ---------------- Status badge ---------------- */

const statusStyles = {
  ready: "bg-source-soft text-source",
  processing: "bg-warn-soft text-warn",
  failed: "bg-danger-soft text-danger",
};

export function StatusBadge({ status }) {
  const style = statusStyles[status] ?? "bg-rule-soft text-muted";
  return (
    <span
      className={`inline-flex items-center rounded-sm px-1.5 py-0.5 font-mono text-[11px] tracking-tight ${style} ${
        status === "processing" ? "pulse-soft" : ""
      }`}
    >
      {status}
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
