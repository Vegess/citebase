import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, PasswordInput } from "./ui";
import { GitHubMark, GoogleMark, Icon } from "./icons";
import { Wordmark } from "./Chrome";
import { useDialog } from "../hooks/useDialog";
import { useSignupMode } from "../hooks/useSignupMode";

const PROVIDER_LABEL = { google: "Google", github: "GitHub" };

function ProviderButton({ provider, enabled }) {
  const [notice, setNotice] = useState("");
  const Mark = provider === "google" ? GoogleMark : GitHubMark;
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          if (enabled) window.location.assign(api.oauthStartUrl(provider));
          else setNotice(`${PROVIDER_LABEL[provider]} sign-in isn't set up on this server yet. Use email for now.`);
        }}
        className="flex w-full items-center justify-center gap-3 rounded-md border border-ink/80 bg-surface px-4 py-2.5 text-sm font-medium text-ink transition-colors hover:bg-rule-soft"
      >
        <Mark />
        Continue with {PROVIDER_LABEL[provider]}
      </button>
      {notice && <p className="mt-1.5 text-xs text-muted">{notice}</p>}
    </div>
  );
}

function Input({ label, ...props }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>
      <input
        className="w-full rounded-md border border-rule bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-muted focus:border-signal focus:outline-none"
        {...props}
      />
    </label>
  );
}

/** Approved access requests get a link to /signup#access=<token>. */
function readAccessToken() {
  return new URLSearchParams(window.location.hash.slice(1)).get("access");
}

/** Waitlist mode: ask for access instead of creating a workspace. */
export function RequestAccessForm({ onSignIn }) {
  const [form, setForm] = useState({ name: "", email: "", company: "", reason: "" });
  const [sent, setSent] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const reply = await api.requestAccess({
        name: form.name,
        email: form.email,
        company: form.company || null,
        reason: form.reason || null,
      });
      setSent(reply.detail);
    } catch (err) {
      setError(err.status === 429 ? "Too many requests from here. Please try again later." : err.detail || "Couldn't send your request.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2 className="font-display text-2xl text-ink">Request access</h2>
      <p className="mt-1 text-sm text-muted">
        Citebase is invite-only while in beta. Tell us a little about you and we'll email you a sign-up link.
      </p>
      {sent ? (
        <p role="status" className="mt-6 rounded-md bg-signal-soft px-3 py-3 text-sm text-ink">
          {sent}
        </p>
      ) : (
        <form onSubmit={submit} className="mt-6 space-y-4">
          <Input label="Name" required maxLength={120} autoComplete="name" value={form.name} onChange={set("name")} />
          <Input
            label="Work email"
            type="email"
            required
            autoComplete="email"
            value={form.email}
            onChange={set("email")}
            placeholder="name@company.com"
          />
          <Input label="Company (optional)" maxLength={120} autoComplete="organization" value={form.company} onChange={set("company")} />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink">What would you use it for? (optional)</span>
            <textarea
              rows={3}
              maxLength={2000}
              value={form.reason}
              onChange={set("reason")}
              className="w-full rounded-md border border-rule bg-surface px-3 py-2.5 text-sm text-ink focus:border-signal focus:outline-none"
            />
          </label>
          {error && (
            <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full py-2.5" disabled={busy}>
            {busy ? "Sending…" : "Request access"}
          </Button>
        </form>
      )}
      <p className="mt-5 text-center text-sm text-muted">
        Already have an account?{" "}
        <button type="button" className="text-signal" onClick={onSignIn}>
          Sign in
        </button>
      </p>
      <p className="mt-3 text-center text-xs text-muted">Joining your team? Use the invite link your admin sent you.</p>
    </div>
  );
}

/**
 * Email-first sign-in, as on Coursera/LeetCode: social buttons on top, then
 * one email field; the password (and workspace name for new accounts) appear
 * after "Continue". Works both inside the modal and as a full page.
 */
export function AuthPanel({ initialMode = "signin", onDone }) {
  const { signIn, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mode, setMode] = useState(initialMode); // signin | signup
  const [step, setStep] = useState("email"); // email | details
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [providers, setProviders] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef(null);
  const signupMode = useSignupMode();
  const [accessToken] = useState(readAccessToken);
  const [accessEmail, setAccessEmail] = useState("");

  useEffect(() => {
    api.getProviders().then((r) => setProviders(r.providers)).catch(() => setProviders([]));
  }, []);

  useEffect(() => {
    if (!accessToken) return;
    // Keep the token out of the address bar and browser history.
    window.history.replaceState(null, "", window.location.pathname);
    setMode("signup");
    api
      .previewAccess(accessToken)
      .then((access) => {
        setAccessEmail(access.email);
        setEmail(access.email);
        setStep("details");
      })
      .catch((err) => setError(err.detail || "This sign-up link can't be used."));
  }, [accessToken]);

  useEffect(() => {
    if (step === "details") passwordRef.current?.focus();
  }, [step]);

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (step === "email") {
      setStep("details");
      return;
    }
    setBusy(true);
    try {
      if (mode === "signin") await signIn(email, password);
      else await register(email, password, orgName, accessToken);
      onDone?.();
      // Back to the page that sent them to sign in, if any.
      navigate(location.state?.from?.pathname || "/home", { replace: true });
    } catch (err) {
      setError(
        err.detail ||
          (mode === "signin" ? "That email and password didn't match." : "Couldn't create the account."),
      );
    } finally {
      setBusy(false);
    }
  }

  const switchMode = (next) => {
    setMode(next);
    setError("");
    setStep(email ? "details" : "email");
  };

  if (mode === "signup" && signupMode === "waitlist" && !accessToken) {
    return <RequestAccessForm onSignIn={() => switchMode("signin")} />;
  }

  return (
    <div>
      <h2 className="font-display text-2xl text-ink">
        {mode === "signin" ? "Sign in to Citebase" : "Create your workspace"}
      </h2>
      <p className="mt-1 text-sm text-muted">
        {mode === "signin"
          ? "Answers from your company's documents, with sources."
          : "Free while in beta. You'll be the owner and can invite your team."}
      </p>

      <div className="mt-6 space-y-2.5">
        <ProviderButton provider="google" enabled={providers.includes("google")} />
        <ProviderButton provider="github" enabled={providers.includes("github")} />
      </div>

      <div className="my-5 flex items-center gap-3 text-xs text-muted">
        <span className="h-px flex-1 bg-rule" /> or with email <span className="h-px flex-1 bg-rule" />
      </div>

      <form onSubmit={submit} className="space-y-4">
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="name@company.com"
          readOnly={Boolean(accessEmail)}
          disabled={Boolean(accessEmail)}
          title={accessEmail ? "Your access was approved for this email." : undefined}
        />
        {step === "details" && (
          <>
            {mode === "signup" && (
              <Input
                label="Workspace name"
                required
                minLength={2}
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                placeholder="Acme Insurance"
              />
            )}
            <PasswordInput
              ref={passwordRef}
              className="py-2.5"
              label="Password"
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              required
              minLength={mode === "signup" ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "signup" ? "At least 8 characters" : ""}
            />
          </>
        )}
        {step === "details" && mode === "signin" && (
          <p className="-mt-2 text-right text-xs">
            <a href="/forgot-password" className="text-signal">
              Forgot password?
            </a>
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
        <Button type="submit" className="w-full py-2.5" disabled={busy}>
          {busy ? "Please wait…" : step === "email" ? "Continue" : mode === "signin" ? "Sign in" : "Create workspace"}
        </Button>
      </form>

      <p className="mt-5 text-center text-sm text-muted">
        {mode === "signin" ? (
          <>
            New to Citebase?{" "}
            <button type="button" className="text-signal" onClick={() => switchMode("signup")}>
              {signupMode === "waitlist" ? "Request access" : "Create a workspace"}
            </button>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <button type="button" className="text-signal" onClick={() => switchMode("signin")}>
              Sign in
            </button>
          </>
        )}
      </p>
      <p className="mt-3 text-center text-xs text-muted">
        Joining your team? Use the invite link your admin sent you. By continuing you agree to our{" "}
        <a href="/privacy" className="underline">
          privacy notice
        </a>
        .
      </p>
    </div>
  );
}

export function AuthModal({ open, mode, onClose }) {
  const dialog = useDialog(onClose, open);
  useEffect(() => {
    if (!open) return undefined;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  if (!open) return null;
  return (
    <div
      ref={dialog}
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-ink/50 px-4 py-10 sm:items-center"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-label={mode === "signin" ? "Sign in" : "Create account"}
    >
      <div className="relative w-full max-w-md rounded-xl bg-surface p-7 shadow-2xl">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute top-4 right-4 rounded-md p-1 text-muted hover:bg-rule-soft hover:text-ink"
        >
          <Icon.Close />
        </button>
        <AuthPanel key={mode} initialMode={mode} onDone={onClose} />
      </div>
    </div>
  );
}

/** Full-page versions for /login and /signup (direct links, bookmarks). */
export function AuthPage({ mode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-5 py-12">
      <a href="/" className="mb-8">
        <Wordmark className="text-2xl" />
      </a>
      <div className="w-full max-w-md rounded-xl border border-rule bg-surface p-7">
        <AuthPanel initialMode={mode} />
      </div>
    </div>
  );
}
