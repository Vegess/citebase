import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Wordmark } from "../components/Chrome";
import { Button, Field } from "../components/ui";
import * as api from "../lib/api";

function AuthShell({ title, blurb, children, footer }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-5 py-12">
      <Link to="/" className="mb-8">
        <Wordmark className="text-2xl" />
      </Link>

      <div className="w-full max-w-sm rounded-lg border border-rule bg-surface p-7">
        <h1 className="font-display text-2xl text-ink">{title}</h1>
        <p className="mt-1 mb-6 text-sm text-muted">{blurb}</p>
        {children}
      </div>

      <p className="mt-5 text-sm text-muted">{footer}</p>
    </div>
  );
}

function ErrorLine({ message }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
      {message}
    </p>
  );
}

export function AcceptInvitePage() {
  const { joinWithInvite } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const inviteToken = location.hash.replace(/^#/, "");
  const [invite, setInvite] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!inviteToken) {
      setLoadError("This invite link is incomplete. Ask your admin to send it again.");
      return;
    }
    api
      .previewInvite(inviteToken)
      .then(setInvite)
      .catch((err) => setLoadError(err.detail || "This invite link can't be used."));
  }, [inviteToken]);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await joinWithInvite(inviteToken, password);
      navigate("/home", { replace: true });
    } catch (err) {
      setError(err.detail || "Couldn't accept the invite.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title={invite ? `Join ${invite.org_name}` : "Join your team"}
      blurb={
        invite
          ? `You've been invited as ${invite.role.toLowerCase()}. Choose a password to finish.`
          : "Checking your invite…"
      }
      footer={
        <>
          Already have an account? <Link to="/login" className="text-signal">Sign in</Link>
        </>
      }
    >
      {loadError ? (
        <ErrorLine message={loadError} />
      ) : (
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Field label="Email" type="email" value={invite?.email ?? ""} disabled readOnly />
          <Field
            label="Password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            hint="At least 8 characters."
          />
          <ErrorLine message={error} />
          <Button type="submit" disabled={busy || !invite}>
            {busy ? "Joining…" : "Join workspace"}
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
