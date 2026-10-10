import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, Field } from "../components/ui";
import { Wordmark } from "../components/Chrome";

function Shell({ title, children }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-paper px-5 py-12">
      <Link to="/" className="mb-8">
        <Wordmark className="text-2xl" />
      </Link>
      <div className="w-full max-w-md rounded-xl border border-rule bg-surface p-7">
        <h1 className="font-display text-2xl text-ink">{title}</h1>
        {children}
      </div>
    </div>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState(null); // null | {email_enabled}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setState(await api.forgotPassword(email));
    } catch (err) {
      setError(err.detail || "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title="Reset your password">
      {state ? (
        state.email_enabled ? (
          <p className="mt-3 text-sm text-ink-soft">
            If <span className="font-medium text-ink">{email}</span> has a Citebase account, a reset link is on its way.
            It works once and expires in an hour.
          </p>
        ) : (
          <p className="mt-3 text-sm text-ink-soft">
            Email isn't set up on this Citebase yet. Ask an admin of your workspace for a reset link: they can create
            one from the Team page.
          </p>
        )
      ) : (
        <form onSubmit={submit} className="mt-5 space-y-4">
          <Field label="Email" type="email" autoComplete="email" required value={email}
            onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" />
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <Button type="submit" className="w-full py-2.5" disabled={busy}>
            {busy ? "Please wait…" : "Send reset link"}
          </Button>
        </form>
      )}
      <p className="mt-5 text-center text-sm">
        <Link to="/login" className="text-signal">
          Back to sign in
        </Link>
      </p>
    </Shell>
  );
}

export function ResetPasswordPage() {
  const { signInWithToken } = useAuth();
  const navigate = useNavigate();
  const tokenRef = useRef(null);
  const [email, setEmail] = useState(null);
  const [invalid, setInvalid] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (tokenRef.current === null) {
      tokenRef.current = window.location.hash.slice(1);
      window.history.replaceState(null, "", window.location.pathname); // keep the token out of history
    }
    if (!tokenRef.current) {
      setInvalid(true);
      return;
    }
    api
      .previewReset(tokenRef.current)
      .then((r) => setEmail(r.email))
      .catch(() => setInvalid(true));
  }, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { access_token } = await api.resetPassword(tokenRef.current, password);
      await signInWithToken(access_token);
      navigate("/home", { replace: true });
    } catch (err) {
      setError(err.detail || "Couldn't reset your password.");
      setBusy(false);
    }
  }

  return (
    <Shell title="Choose a new password">
      {invalid ? (
        <>
          <p className="mt-3 text-sm text-ink-soft">This reset link is invalid, already used, or expired.</p>
          <p className="mt-5 text-sm">
            <Link to="/forgot-password" className="text-signal">
              Get a new link
            </Link>
          </p>
        </>
      ) : !email ? (
        <p className="mt-3 text-sm text-muted">Checking your link…</p>
      ) : (
        <form onSubmit={submit} className="mt-5 space-y-4">
          <p className="text-sm text-ink-soft">
            For <span className="font-medium text-ink">{email}</span>. Every device signed in to this account will be
            signed out.
          </p>
          <Field label="New password" type="password" autoComplete="new-password" required minLength={8} value={password}
            onChange={(e) => setPassword(e.target.value)} hint="At least 8 characters." />
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <Button type="submit" className="w-full py-2.5" disabled={busy}>
            {busy ? "Saving…" : "Save and sign in"}
          </Button>
        </form>
      )}
    </Shell>
  );
}
