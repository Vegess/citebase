import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { hasRole, useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, Field, LoadError, useToast } from "../components/ui";
import { GitHubMark, GoogleMark, Icon } from "../components/icons";

const PROVIDER = {
  github: { label: "GitHub", Mark: GitHubMark },
  google: { label: "Google", Mark: GoogleMark },
};

const LINK_ERRORS = {
  email_mismatch: "That account uses a different email address. Connect one that uses the same email as Citebase.",
  cancelled: "Connecting was cancelled.",
  expired: "That took too long. Please try again.",
  state_mismatch: "We couldn't verify that attempt. Please try again from this page.",
  no_verified_email: "That account has no verified email address.",
  provider_error: "The provider didn't respond. Please try again.",
  account_removed: "This account was removed from its workspace.",
};

function Section({ title, hint, children, tone }) {
  return (
    <section
      className={`rounded-xl border p-6 ${tone === "danger" ? "border-danger/40 bg-danger-soft/30" : "border-rule bg-surface"}`}
    >
      <h2 className={`font-display text-xl ${tone === "danger" ? "text-danger" : "text-ink"}`}>{title}</h2>
      {hint && <p className="mt-0.5 text-sm text-muted">{hint}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function PasswordForm({ account, onChanged }) {
  const { token } = useAuth();
  const notify = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { access_token } = await api.changePassword(token, current, next);
      setCurrent("");
      setNext("");
      notify("Password saved. Other devices have been signed out.", "info");
      await onChanged(access_token);
    } catch (err) {
      setError(err.detail || "Couldn't change your password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid max-w-md gap-3">
      {account.password_set ? (
        <Field label="Current password" type="password" autoComplete="current-password" required value={current}
          onChange={(e) => setCurrent(e.target.value)} />
      ) : (
        <p className="text-sm text-muted">
          You sign in with {account.identities.map((i) => PROVIDER[i.provider]?.label).join(" or ")}. Add a password
          to also sign in with your email.
        </p>
      )}
      <Field label={account.password_set ? "New password" : "Password"} type="password" autoComplete="new-password"
        required minLength={8} value={next} onChange={(e) => setNext(e.target.value)} hint="At least 8 characters." />
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : account.password_set ? "Change password" : "Set password"}
        </Button>
      </div>
    </form>
  );
}

function DangerZone({ orgName }) {
  const { token, signOut } = useAuth();
  const navigate = useNavigate();
  const [confirmName, setConfirmName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleDelete(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.deleteWorkspace(token, confirmName);
      signOut();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.detail || "Couldn't delete the workspace.");
      setBusy(false);
    }
  }

  return (
    <Section
      tone="danger"
      title="Delete workspace"
      hint={`Permanently removes ${orgName}: every member, document, conversation and audit entry. This can't be undone.`}
    >
      <form onSubmit={handleDelete} className="flex flex-col gap-2 sm:flex-row">
        <label className="flex-1">
          <span className="sr-only">Type the workspace name to confirm</span>
          <input
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            placeholder={`Type "${orgName}" to confirm`}
            className="w-full rounded-md border border-rule bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-danger focus:outline-none"
          />
        </label>
        <Button type="submit" variant="danger" disabled={busy || confirmName !== orgName}>
          {busy ? "Deleting…" : "Delete workspace"}
        </Button>
      </form>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
    </Section>
  );
}

function WorkspaceName() {
  const { token, user, refreshUser } = useAuth();
  const notify = useToast();
  const [name, setName] = useState(user?.org_name || "");
  const [busy, setBusy] = useState(false);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.renameWorkspace(token, name);
      await refreshUser();
      notify("Workspace renamed.", "info");
    } catch (err) {
      notify(err.detail || "Couldn't rename the workspace.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Workspace" hint="Everyone in the workspace sees this name.">
      <form onSubmit={save} className="flex max-w-md items-end gap-2">
        <div className="flex-1">
          <Field label="Name" required minLength={2} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <Button type="submit" variant="secondary" disabled={busy || name.trim() === user?.org_name}>
          Save
        </Button>
      </form>
    </Section>
  );
}

export default function SettingsPage() {
  const { token, user, signInWithToken, signOut } = useAuth();
  const notify = useToast();
  const navigate = useNavigate();
  const [account, setAccount] = useState(null);
  const [banner, setBanner] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setAccount(await api.getAccount(token));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  // Coming back from connecting GitHub/Google: #linked=github or #error=...
  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    if (!params.toString()) return;
    window.history.replaceState(null, "", window.location.pathname);
    if (params.get("linked")) {
      setBanner({ ok: true, text: `${PROVIDER[params.get("linked")]?.label ?? "Account"} connected. You can now sign in with it.` });
    } else if (params.get("error")) {
      setBanner({ ok: false, text: LINK_ERRORS[params.get("error")] || "Connecting didn't work. Please try again." });
    }
  }, []);

  async function sendVerification() {
    try {
      await api.requestVerification(token);
      notify(`Sent. Check ${account.email} for the link.`, "info");
    } catch (err) {
      notify(err.detail || "Couldn't send the email.");
    }
  }

  async function connect(provider) {
    try {
      const { url } = await api.linkProvider(token, provider);
      window.location.assign(url);
    } catch (err) {
      notify(err.detail || "Couldn't start connecting.");
    }
  }

  async function disconnect(provider) {
    if (!window.confirm(`Disconnect ${PROVIDER[provider].label}? You won't be able to sign in with it.`)) return;
    try {
      await api.unlinkProvider(token, provider);
      await load();
    } catch (err) {
      notify(err.detail || "Couldn't disconnect.");
    }
  }

  async function everywhere() {
    if (!window.confirm("Sign out on every device, including this one?")) return;
    try {
      await api.signOutEverywhere(token);
    } finally {
      signOut();
      navigate("/login", { replace: true });
    }
  }

  const providers = account
    ? Array.from(new Set([...account.available_providers, ...account.identities.map((i) => i.provider)]))
    : [];

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-5 py-10">
      <div>
        <h1 className="font-display text-3xl text-ink">Settings</h1>
        <p className="mt-1 text-sm text-muted">Your account and, for admins, the workspace.</p>
      </div>

      {banner && (
        <p
          role="status"
          className={`rounded-lg px-4 py-3 text-sm ${banner.ok ? "bg-source-soft text-source" : "bg-danger-soft text-danger"}`}
        >
          {banner.text}
        </p>
      )}

      {!account && failed ? (
        <LoadError onRetry={load} />
      ) : !account ? (
        <div className="h-48 rounded-xl border border-rule bg-surface pulse-soft" />
      ) : (
        <>
          <Section title="Account">
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-[10rem_1fr]">
              <dt className="text-muted">Email</dt>
              <dd className="flex flex-wrap items-center gap-2 text-ink">
                {account.email}
                {account.email_verified ? (
                  <span className="rounded-sm bg-source-soft px-1.5 py-0.5 text-[11px] font-medium text-source">Verified</span>
                ) : (
                  <span className="rounded-sm bg-rule-soft px-1.5 py-0.5 text-[11px] text-muted">Not verified</span>
                )}
              </dd>
              <dt className="text-muted">Workspace</dt>
              <dd className="text-ink">{account.org_name}</dd>
              <dt className="text-muted">Role</dt>
              <dd className="font-mono text-xs text-ink">{account.role.toLowerCase()}</dd>
            </dl>
            {!account.email_verified && (
              <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg bg-rule-soft px-3 py-2.5 text-xs text-ink-soft">
                <span className="flex-1">
                  {account.email_enabled
                    ? "Confirm your email to invite teammates. Connecting Google or GitHub below also confirms it."
                    : "Connect Google or GitHub below to confirm your email. Then you can also sign in with it."}
                </span>
                {account.email_enabled && (
                  <Button size="sm" variant="secondary" onClick={sendVerification}>
                    Send confirmation email
                  </Button>
                )}
              </div>
            )}
          </Section>

          <Section title="Sign-in methods" hint="Connect an account that uses the same email address.">
            <ul className="divide-y divide-rule rounded-lg border border-rule">
              <li className="flex items-center gap-3 px-4 py-3 text-sm">
                <Icon.Lock width={18} height={18} className="text-muted" />
                <span className="flex-1 text-ink">Email and password</span>
                <span className="text-xs text-muted">{account.password_set ? "On" : "Not set"}</span>
              </li>
              {providers.map((p) => {
                const linked = account.identities.find((i) => i.provider === p);
                const { label, Mark } = PROVIDER[p] ?? { label: p, Mark: () => null };
                const canConnect = account.available_providers.includes(p);
                return (
                  <li key={p} className="flex items-center gap-3 px-4 py-3 text-sm">
                    <Mark />
                    <span className="flex-1 text-ink">
                      {label}
                      {linked && <span className="block text-xs text-muted">{linked.email}</span>}
                    </span>
                    {linked ? (
                      <Button variant="ghost" size="sm" onClick={() => disconnect(p)}>
                        Disconnect
                      </Button>
                    ) : (
                      <Button variant="secondary" size="sm" disabled={!canConnect} onClick={() => connect(p)}>
                        Connect
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          </Section>

          <Section title={account.password_set ? "Change password" : "Add a password"}>
            <PasswordForm account={account} onChanged={(t) => signInWithToken(t)} />
          </Section>

          <Section
            title="Devices"
            hint={`Signed in on ${account.active_sessions} device${account.active_sessions === 1 ? "" : "s"}. Sessions end after 30 days without use.`}
          >
            <Button variant="secondary" onClick={everywhere}>
              Sign out everywhere
            </Button>
          </Section>

          {hasRole(user, "ADMIN") && <WorkspaceName />}
          {user?.role === "OWNER" && user.org_name && <DangerZone orgName={user.org_name} />}
        </>
      )}
    </main>
  );
}
