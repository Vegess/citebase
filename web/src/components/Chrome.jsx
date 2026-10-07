import { Navigate, NavLink, useLocation } from "react-router-dom";
import { hasRole, useAuth } from "../context/AuthContext";
import { Button } from "./ui";

export function Wordmark({ className = "" }) {
  return (
    <span className={`font-display text-xl tracking-tight text-ink ${className}`}>
      Docu<span className="text-source">Mind</span>
    </span>
  );
}

export function ProtectedRoute({ children }) {
  const { isAuthed } = useAuth();
  const location = useLocation();
  if (!isAuthed) return <Navigate to="/login" state={{ from: location }} replace />;
  return children;
}

const linkClass = ({ isActive }) =>
  `rounded-md px-2.5 py-1.5 text-sm transition-colors ${
    isActive ? "bg-rule-soft text-ink" : "text-ink-soft hover:text-ink"
  }`;

export function Navbar() {
  const { user, signOut } = useAuth();

  return (
    <header className="border-b border-rule bg-surface">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-5">
        <Wordmark />

        <nav className="flex items-center gap-1">
          <NavLink to="/documents" className={linkClass}>
            Documents
          </NavLink>
          <NavLink to="/chat" className={linkClass}>
            Ask
          </NavLink>
          {hasRole(user, "ADMIN") && (
            <NavLink to="/team" className={linkClass}>
              Team
            </NavLink>
          )}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          {user && (
            <span className="hidden text-right sm:block">
              <span className="block text-xs text-ink">{user.email}</span>
              {user.org_name && (
                <span className="block font-mono text-[11px] text-muted">
                  {user.org_name} · {user.role?.toLowerCase()}
                </span>
              )}
            </span>
          )}
          <Button variant="ghost" onClick={signOut}>
            Sign out
          </Button>
        </div>
      </div>
    </header>
  );
}
