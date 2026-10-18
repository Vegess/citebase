import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, useLocation } from "react-router-dom";
import { hasRole, useAuth } from "../context/AuthContext";
import { Icon } from "./icons";
import { useDialog } from "../hooks/useDialog";

/** The app mark: a document with a [1] citation badge. Same art as /favicon.svg. */
export function LogoMark({ className = "h-[1.2em] w-[1.2em]" }) {
  return (
    <svg viewBox="0 0 512 512" className={`shrink-0 ${className}`} aria-hidden="true">
      <rect width="512" height="512" rx="112" fill="#2d5bff" />
      <path d="M150 104h150l70 70v234a24 24 0 0 1-24 24H150a24 24 0 0 1-24-24V128a24 24 0 0 1 24-24z" fill="#fff" />
      <path d="M300 104v54a16 16 0 0 0 16 16h54z" fill="#c9d6ff" />
      <rect x="166" y="210" width="150" height="20" rx="10" fill="#2d5bff" opacity=".35" />
      <rect x="166" y="254" width="120" height="20" rx="10" fill="#2d5bff" opacity=".35" />
      <circle cx="330" cy="352" r="72" fill="#0f8a7a" stroke="#2d5bff" strokeWidth="14" />
      <path d="M296 322h-12v60h12M364 322h12v60h-12" fill="none" stroke="#fff" strokeWidth="12" strokeLinejoin="round" />
      <path d="M320 334l12-8v56" fill="none" stroke="#fff" strokeWidth="12" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Wordmark({ className = "", light = false }) {
  return (
    <span
      className={`inline-flex items-center gap-2 font-display text-xl tracking-tight ${light ? "text-paper" : "text-ink"} ${className}`}
    >
      <LogoMark />
      <span>
        Cite<span className={light ? "text-[#7fd6c8]" : "text-source"}>base</span>
      </span>
    </span>
  );
}

export function ProtectedRoute({ children }) {
  const { isAuthed, restoring } = useAuth();
  const location = useLocation();
  if (!isAuthed && restoring) return <FullPageNote>Signing you back in…</FullPageNote>;
  if (!isAuthed) return <Navigate to="/login" state={{ from: location }} replace />;
  return children;
}

/** Pages only admins can use; others go Home instead of hitting a 403. */
export function AdminOnly({ children }) {
  const { user } = useAuth();
  if (user && !hasRole(user, "ADMIN")) return <Navigate to="/home" replace />;
  return children;
}

/** Platform admins (PLATFORM_ADMIN_EMAILS) review access requests. */
export function PlatformAdminOnly({ children }) {
  const { user } = useAuth();
  if (user && !user.is_platform_admin) return <Navigate to="/home" replace />;
  return children;
}

/** Sends signed-in people past the sign-in pages. */
export function GuestOnly({ children }) {
  const { isAuthed, restoring } = useAuth();
  const location = useLocation();
  if (isAuthed) return <Navigate to={location.state?.from?.pathname || "/home"} replace />;
  if (restoring) return <FullPageNote>Signing you back in…</FullPageNote>;
  return children;
}

export function FullPageNote({ children }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-paper px-5 text-center">
      <Wordmark className="text-2xl" />
      <p className="text-sm text-muted">{children}</p>
    </div>
  );
}

const NAV = [
  { to: "/home", label: "Home", icon: Icon.Home, hint: "What needs attention" },
  { to: "/chat", label: "Ask", icon: Icon.Chat, hint: "Questions and deep research" },
  { to: "/documents", label: "Documents", icon: Icon.Doc, hint: "Upload and track processing" },
  { to: "/insights", label: "Insights", icon: Icon.Chart, hint: "Gaps, conflicts, usage", minRole: "ADMIN" },
  { to: "/team", label: "Team", icon: Icon.Users, hint: "Members, invites, audit", minRole: "ADMIN" },
  { to: "/settings", label: "Settings", icon: Icon.Gear, hint: "Account and workspace" },
  { to: "/admin/access", label: "Access requests", icon: Icon.Lock, hint: "Approve waitlist sign-ups", platformAdmin: true },
];

function initials(email = "") {
  const name = email.split("@")[0] || "?";
  const parts = name.split(/[._-]+/).filter(Boolean);
  return ((parts[0]?.[0] || "") + (parts[1]?.[0] || "")).toUpperCase() || name[0].toUpperCase();
}

function SidebarContents({ onNavigate }) {
  const { user, signOut } = useAuth();
  const items = NAV.filter(
    (n) => (!n.minRole || hasRole(user, n.minRole)) && (!n.platformAdmin || user?.is_platform_admin),
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center px-4">
        <Link to="/home" onClick={onNavigate}>
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
  const drawer = useDialog(() => setOpen(false), open);

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
        <div ref={drawer} className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
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
