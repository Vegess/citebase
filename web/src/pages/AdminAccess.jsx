import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, EmptyState, useToast } from "../components/ui";

const FILTERS = [
  ["pending", "Pending"],
  ["approved", "Approved"],
  ["rejected", "Rejected"],
  ["", "All"],
];

const when = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");

/** Platform admins approve or reject waitlist requests (SIGNUP_MODE=waitlist). */
export default function AdminAccessPage() {
  const { token } = useAuth();
  const notify = useToast();
  const [filter, setFilter] = useState("pending");
  const [requests, setRequests] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [manualLink, setManualLink] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setRequests(await api.listAccessRequests(token, filter));
    } catch (err) {
      notify(err.detail || "Couldn't load access requests.");
    }
  }, [token, filter, notify]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function decide(request, approve) {
    setBusyId(request.id);
    try {
      if (approve) {
        const result = await api.approveAccessRequest(token, request.id);
        if (result.emailed) {
          setManualLink(null);
          notify(`Sign-up link emailed to ${request.email}.`, "info");
        } else {
          setManualLink({ email: request.email, url: result.link });
        }
      } else {
        await api.rejectAccessRequest(token, request.id);
        notify(`Rejected ${request.email}.`, "info");
      }
      await refresh();
    } catch (err) {
      notify(err.detail || "Couldn't update the request.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-5 py-10">
      <h1 className="font-display text-3xl text-ink">Access requests</h1>
      <p className="mt-1 text-sm text-muted">
        Approving emails a sign-up link that works once and expires after 7 days. Approving again sends a fresh link.
      </p>

      <div className="mt-6 flex flex-wrap gap-2" role="tablist" aria-label="Filter requests">
        {FILTERS.map(([value, label]) => (
          <button
            key={label}
            type="button"
            role="tab"
            aria-selected={filter === value}
            onClick={() => setFilter(value)}
            className={`rounded-full px-3 py-1 text-sm ${
              filter === value ? "bg-ink text-paper" : "border border-rule text-ink-soft hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {manualLink && (
        <div className="mt-6 rounded-lg border border-rule bg-surface p-4 text-sm">
          <p className="text-ink">
            Email isn't set up, so send this link to <strong>{manualLink.email}</strong> yourself:
          </p>
          <div className="mt-2 flex gap-2">
            <input readOnly value={manualLink.url} className="flex-1 rounded-md border border-rule bg-paper px-3 py-2 font-mono text-xs" />
            <Button
              size="sm"
              variant="secondary"
              onClick={() => navigator.clipboard?.writeText(manualLink.url).then(() => notify("Link copied.", "info"))}
            >
              Copy
            </Button>
          </div>
        </div>
      )}

      <section className="mt-6">
        {requests === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : requests.length === 0 ? (
          <EmptyState title="Nothing here">No {filter || ""} requests right now.</EmptyState>
        ) : (
          <ul className="divide-y divide-rule rounded-lg border border-rule bg-surface">
            {requests.map((r) => (
              <li key={r.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="font-medium text-ink">
                    {r.name} <span className="font-normal text-muted">· {r.email}</span>
                  </p>
                  {r.company && <p className="text-sm text-ink-soft">{r.company}</p>}
                  {r.reason && <p className="mt-1 text-sm whitespace-pre-line text-ink-soft">{r.reason}</p>}
                  <p className="mt-1 font-mono text-[11px] text-muted">
                    {r.status} · asked {when(r.created_at)}
                    {r.decided_at ? ` · decided ${when(r.decided_at)}` : ""}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button size="sm" disabled={busyId === r.id} onClick={() => decide(r, true)}>
                    {r.status === "approved" ? "Resend link" : "Approve"}
                  </Button>
                  {r.status !== "rejected" && (
                    <Button size="sm" variant="danger" disabled={busyId === r.id} onClick={() => decide(r, false)}>
                      Reject
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
