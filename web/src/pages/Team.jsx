import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, EmptyState, useToast } from "../components/ui";

const ROLE_HELP = {
  ADMIN: "Invites people, manages roles, removes any document",
  MEMBER: "Uploads documents and asks questions",
  VIEWER: "Asks questions only",
};

const ACTION_LABELS = {
  "org.created": "created the workspace",
  "invite.created": "sent an invite",
  "invite.revoked": "revoked an invite",
  "invite.accepted": "joined via invite",
  "member.role_changed": "changed a role",
  "member.removed": "removed a member",
  "document.uploaded": "uploaded a document",
  "document.deleted": "removed a document",
};

const RANK = { VIEWER: 0, MEMBER: 1, ADMIN: 2, OWNER: 3 };

function grantableRoles(actorRole) {
  return Object.keys(ROLE_HELP).filter((role) => actorRole === "OWNER" || RANK[role] < RANK[actorRole]);
}

function describeDetails(details) {
  if (!details) return "";
  try {
    const d = JSON.parse(details);
    if (d.from && d.to) return `${d.from.toLowerCase()} → ${d.to.toLowerCase()}`;
    return d.filename || d.email || (d.role ? d.role.toLowerCase() : "");
  } catch {
    return "";
  }
}

function DangerZone({ token, orgName, onDeleted }) {
  const [confirmName, setConfirmName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleDelete(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.deleteWorkspace(token, confirmName);
      onDeleted();
    } catch (err) {
      setError(err.detail || "Couldn't delete the workspace.");
      setBusy(false);
    }
  }

  return (
    <section className="mt-12 rounded-lg border border-danger/40 bg-danger-soft/40 p-5">
      <h2 className="font-display text-xl text-danger">Delete workspace</h2>
      <p className="mt-1 text-sm text-ink-soft">
        Permanently removes <span className="font-medium text-ink">{orgName}</span>: every member, document,
        conversation and audit entry. This can't be undone.
      </p>
      <form onSubmit={handleDelete} className="mt-4 flex flex-col gap-2 sm:flex-row">
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
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  );
}

function SectionTitle({ children, hint }) {
  return (
    <div className="mb-3">
      <h2 className="font-display text-xl text-ink">{children}</h2>
      {hint && <p className="mt-0.5 text-sm text-muted">{hint}</p>}
    </div>
  );
}

export default function TeamPage() {
  const { token, user, signOut } = useAuth();
  const navigate = useNavigate();
  const notify = useToast();
  const [members, setMembers] = useState([]);
  const [invites, setInvites] = useState([]);
  const [events, setEvents] = useState([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("MEMBER");
  const [busy, setBusy] = useState(false);
  const [freshLink, setFreshLink] = useState(null);

  const roles = grantableRoles(user?.role);

  const refresh = useCallback(async () => {
    try {
      const [m, i, a] = await Promise.all([
        api.listMembers(token),
        api.listInvites(token),
        api.listAudit(token, 25),
      ]);
      setMembers(m);
      setInvites(i);
      setEvents(a);
    } catch (err) {
      notify(err.detail || "Couldn't load your team.");
    }
  }, [token, notify]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const emailFor = (id) => members.find((m) => m.id === id)?.email ?? "Someone";

  async function handleInvite(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const created = await api.createInvite(token, email, role);
      setFreshLink({ email: created.email, url: `${window.location.origin}/invite#${created.token}` });
      setEmail("");
      await refresh();
    } catch (err) {
      notify(err.detail || "Couldn't create the invite.");
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(freshLink.url);
      notify("Invite link copied", "info");
    } catch {
      notify("Copy failed — select the link and copy it manually.");
    }
  }

  async function handleRoleChange(member, nextRole) {
    try {
      await api.changeMemberRole(token, member.id, nextRole);
      await refresh();
    } catch (err) {
      notify(err.detail || "Couldn't change that role.");
    }
  }

  async function handleRemove(member) {
    if (!window.confirm(`Remove ${member.email}? They will be signed out immediately.`)) return;
    try {
      await api.removeMember(token, member.id);
      await refresh();
    } catch (err) {
      notify(err.detail || "Couldn't remove that member.");
    }
  }

  async function handleRevoke(invite) {
    try {
      await api.revokeInvite(token, invite.id);
      await refresh();
    } catch (err) {
      notify(err.detail || "Couldn't revoke that invite.");
    }
  }

  const canManage = (member) =>
    member.id !== user?.id && member.is_active && RANK[member.role] < RANK[user?.role];

  return (
    <main className="mx-auto max-w-4xl px-5 py-10">
      <h1 className="font-display text-3xl text-ink">Team</h1>
      <p className="mt-1 text-sm text-muted">
        People in {user?.org_name ?? "your workspace"}. Only invited people can join.
      </p>

      <section className="mt-8 rounded-lg border border-rule bg-surface p-5">
        <SectionTitle hint="Invite links work once and expire after 7 days.">Invite someone</SectionTitle>
        <form onSubmit={handleInvite} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex-1">
            <span className="mb-1.5 block text-sm font-medium text-ink">Work email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com"
              className="w-full rounded-md border border-rule bg-paper px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-signal focus:outline-none"
            />
          </label>
          <label>
            <span className="mb-1.5 block text-sm font-medium text-ink">Role</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full rounded-md border border-rule bg-paper px-3 py-2 text-sm text-ink focus:border-signal focus:outline-none sm:w-36"
            >
              {roles.map((r) => (
                <option key={r} value={r}>
                  {r.charAt(0) + r.slice(1).toLowerCase()}
                </option>
              ))}
            </select>
          </label>
          <Button type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create invite link"}
          </Button>
        </form>
        <p className="mt-2 text-xs text-muted">{ROLE_HELP[role]}</p>

        {freshLink && (
          <div className="mt-4 rounded-md border border-source/25 bg-source-soft p-3">
            <p className="text-sm text-source">
              Send this link to {freshLink.email}. It is shown only once.
            </p>
            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
              <input
                readOnly
                value={freshLink.url}
                onFocus={(e) => e.target.select()}
                className="min-w-0 flex-1 rounded-md border border-rule bg-paper px-3 py-1.5 font-mono text-xs text-ink"
              />
              <Button variant="secondary" size="sm" onClick={copyLink}>
                Copy link
              </Button>
            </div>
          </div>
        )}
      </section>

      <section className="mt-8">
        <SectionTitle>Members</SectionTitle>
        <ul className="divide-y divide-rule overflow-hidden rounded-lg border border-rule bg-surface">
          {members.map((member) => (
            <li key={member.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className={`truncate text-sm ${member.is_active ? "text-ink" : "text-muted line-through"}`}>
                  {member.email}
                  {member.id === user?.id && <span className="ml-2 text-xs text-muted">(you)</span>}
                </p>
                <p className="mt-0.5 font-mono text-[11px] text-muted">
                  {member.is_active ? "active" : "removed"} · joined {new Date(member.created_at).toLocaleDateString()}
                </p>
              </div>
              {canManage(member) ? (
                <>
                  <select
                    aria-label={`Role for ${member.email}`}
                    value={member.role}
                    onChange={(e) => handleRoleChange(member, e.target.value)}
                    className="rounded-md border border-rule bg-paper px-2 py-1 text-xs text-ink"
                  >
                    {[...new Set([member.role, ...roles])].map((r) => (
                      <option key={r} value={r}>
                        {r.charAt(0) + r.slice(1).toLowerCase()}
                      </option>
                    ))}
                  </select>
                  <Button variant="danger" size="sm" onClick={() => handleRemove(member)}>
                    Remove
                  </Button>
                </>
              ) : (
                <span className="rounded-sm bg-rule-soft px-2 py-0.5 font-mono text-[11px] text-ink-soft">
                  {member.role.toLowerCase()}
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-8">
        <SectionTitle>Pending invites</SectionTitle>
        {invites.length === 0 ? (
          <EmptyState title="No pending invites">New invites appear here until they're accepted.</EmptyState>
        ) : (
          <ul className="divide-y divide-rule overflow-hidden rounded-lg border border-rule bg-surface">
            {invites.map((invite) => (
              <li key={invite.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-ink">{invite.email}</p>
                  <p className="mt-0.5 font-mono text-[11px] text-muted">
                    {invite.role.toLowerCase()} · expires {new Date(invite.expires_at).toLocaleDateString()}
                  </p>
                </div>
                <Button variant="danger" size="sm" onClick={() => handleRevoke(invite)}>
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-8">
        <SectionTitle hint="Security-relevant changes in this workspace.">Recent activity</SectionTitle>
        {events.length === 0 ? (
          <EmptyState title="Nothing yet">Invites, role changes and uploads will be listed here.</EmptyState>
        ) : (
          <ol className="space-y-2">
            {events.map((event) => (
              <li key={event.id} className="flex gap-3 text-sm">
                <span className="w-28 shrink-0 font-mono text-[11px] leading-5 text-muted">
                  {new Date(event.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}
                </span>
                <span className="text-ink">
                  {emailFor(event.actor_id)} {ACTION_LABELS[event.action] ?? event.action}
                  {describeDetails(event.details) && (
                    <span className="text-muted"> · {describeDetails(event.details)}</span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
      {user?.role === "OWNER" && user.org_name && (
        <DangerZone
          token={token}
          orgName={user.org_name}
          onDeleted={() => {
            signOut();
            navigate("/", { replace: true });
          }}
        />
      )}
    </main>
  );
}
