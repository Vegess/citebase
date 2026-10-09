import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, useLocation } from "react-router-dom";
import { hasRole, useAuth } from "../context/AuthContext";
import { Icon } from "./icons";

export function Wordmark({ className = "", light = false }) {
  return (
    <span className={`font-display text-xl tracking-tight ${light ? "text-paper" : "text-ink"} ${className}`}>
      Docu<span className={light ? "text-[#7fd6c8]" : "text-source"}>Mind</span>
    </span>
  );
}

export function ProtectedRoute({ children }) {
  const { isAuthed } = useAuth();
  const location = useLocation();
  if (!isAuthed) return <Navigate to="/login" state={{ from: location }} replace />;
  return children;
}

const NAV = [
  { to: "/chat", label: "Ask", icon: Icon.Chat, hint: "Questions and deep research" },
  { to: "/documents", label: "Documents", icon: Icon.Doc, hint: "Upload and track processing" },
  { to: "/insights", label: "Insights", icon: Icon.Chart, hint: "Gaps, conflicts, usage", minRole: "ADMIN" },
  { to: "/team", label: "Team", icon: Icon.Users, hint: "Members, invites, audit", minRole: "ADMIN" },
];

function initials(email = "") {
  const name = email.split("@")[0] || "?";
  const parts = name.split(/[._-]+/).filter(Boolean);
  return ((parts[0]?.[0] || "") + (parts[1]?.[0] || "")).toUpperCase() || name[0].toUpperCase();
}

function SidebarContents({ onNavigate }) {
  const { user, signOut } = useAuth();
  const items = NAV.filter((n) => !n.minRole || hasRole(user, n.minRole));

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center px-4">
        <Link to="/chat" onClick={onNavigate}>
          <Wordmark />
        </Link>
      </div>

      <div className="px-3">
        <Link
          to="/chat"
          state={{ fresh: Date.now() }}
          onClick={onNavigate}
          className="flex items-center gap-2 rounded-lg bg-signal px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-signal/90"
        >
          <span className="text-lg leading-none">+</span> New question
        </Link>
      </div>

      <nav className="mt-4 flex-1 space-y-0.5 px-3" aria-label="Main">
        {items.map(({ to, label, icon: I, hint }) => (
          <NavLink
            key={to}
            to={to}
            onClick={onNavigate}
            className={({ isActive }) =>
              `group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                isActive ? "bg-rule-soft font-medium text-ink" : "text-ink-soft hover:bg-rule-soft/60 hover:text-ink"
              }`
            }
          >
            <I width={18} height={18} />
            <span className="flex-1">
              {label}
              <span className="block text-[11px] font-normal text-muted">{hint}</span>
            </span>
          </NavLink>
        ))}
      </nav>

      <div className="m-3 rounded-lg border border-rule bg-paper p-3">
        <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">
          <Icon.Shield width={14} height={14} /> Private workspace
        </p>
        <p className="mt-1 text-xs text-ink-soft">
          Only members of <span className="font-medium text-ink">{user?.org_name || "this workspace"}</span> can see
          its documents.
        </p>
      </div>

      {user && (
        <div className="flex items-center gap-3 border-t border-rule px-4 py-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-source/15 text-xs font-semibold text-source">
            {initials(user.email)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs text-ink">{user.email}</span>
            <span className="block truncate font-mono text-[11px] text-muted">{user.role?.toLowerCase()}</span>
          </span>
          <button
            type="button"
            onClick={signOut}
            aria-label="Sign out"
            title="Sign out"
            className="rounded-md p-1.5 text-muted hover:bg-rule-soft hover:text-ink"
          >
            <Icon.Logout width={18} height={18} />
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Signed-in layout, modelled on chat-first assistants: a fixed left sidebar on
 * desktop, a top bar with a slide-in drawer on phones.
 */
export function AppLayout({ children }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="min-h-dvh bg-paper">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-rule bg-surface lg:block">
        <SidebarContents />
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-rule bg-surface px-4 lg:hidden">
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Open menu"
          className="rounded-md p-1.5 text-ink hover:bg-rule-soft"
        >
          <Icon.Menu />
        </button>
        <Wordmark />
      </header>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 bg-ink/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-surface shadow-xl">
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close menu"
              className="absolute top-3.5 right-3 rounded-md p-1 text-muted hover:bg-rule-soft"
            >
              <Icon.Close />
            </button>
            <SidebarContents onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <div className="lg:pl-64">{children}</div>
    </div>
  );
}
