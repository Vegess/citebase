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

export function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(email, password);
      navigate("/documents", { replace: true });
    } catch (err) {
      setError(err.detail || "That email and password combination didn't match.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Sign in"
      blurb="Ask questions across your organisation's documents."
      footer={
        <>
          No account yet? <Link to="/signup" className="text-signal">Create one</Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <ErrorLine message={error} />
        <Button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthShell>
  );
}

export function SignupPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await register(email, password, orgName);
      navigate("/documents", { replace: true });
    } catch (err) {
      setError(err.detail || "Couldn't create the account. Try a different email.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Create an account"
      blurb="Start a new workspace for your organisation. Joining an existing team? Ask an admin for an invite link."
      footer={
        <>
          Already registered? <Link to="/login" className="text-signal">Sign in</Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Field
          label="Organisation"
          placeholder="Acme Insurance"
          required
          value={orgName}
          onChange={(e) => setOrgName(e.target.value)}
          hint="You'll be its owner and can invite your team afterwards."
        />
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
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
        <Button type="submit" disabled={busy}>
          {busy ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthShell>
  );
}

/**
 * Invite links look like /invite#<token>. The token sits in the URL fragment,
 * which browsers never send to servers or in Referer headers.
 */
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
      navigate("/chat", { replace: true });
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
