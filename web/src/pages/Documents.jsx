import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { hasRole, useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, EmptyState, IN_PROGRESS, StatusBadge, useToast } from "../components/ui";
import { DemoBanner } from "../components/DemoBanner";
import { Icon } from "../components/icons";
import { useDialog } from "../hooks/useDialog";

const POLL_MS = 2000;
const ALL = "__all__";
const GENERAL = "__general__";

const FILTERS = [
  ["all", "All statuses"],
  ["ready", "Ready"],
  ["processing", "Processing"],
  ["failed", "Failed"],
  ["conflicts", "Possible conflicts"],
];

function CollectionModal({ collection, onClose, onSaved }) {
  const { token } = useAuth();
  const notify = useToast();
  const [name, setName] = useState(collection?.name || "");
  const [description, setDescription] = useState(collection?.description || "");
  const [restricted, setRestricted] = useState(collection?.restricted || false);
  const [memberIds, setMemberIds] = useState(new Set(collection?.member_ids || []));
  const [people, setPeople] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listMembers(token).then((m) => setPeople(m.filter((p) => p.is_active))).catch(() => setPeople([]));
  }, [token]);

  const dialog = useDialog(onClose);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    const body = { name, description, restricted, member_ids: Array.from(memberIds) };
    try {
      const saved = collection ? await api.updateCollection(token, collection.id, body) : await api.createCollection(token, body);
      onSaved(saved);
    } catch (err) {
      notify(err.detail || "Couldn't save the collection.");
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete the collection "${collection.name}"?`)) return;
    try {
      await api.deleteCollection(token, collection.id);
      onSaved(null);
    } catch (err) {
      notify(err.detail || "Couldn't delete the collection.");
    }
  }

  const toggle = (id) =>
    setMemberIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div ref={dialog} className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 px-4 py-10" role="dialog"
      aria-modal="true" aria-label="Collection" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form onSubmit={save} className="w-full max-w-lg rounded-xl bg-surface p-6 shadow-2xl">
        <h2 className="font-display text-2xl text-ink">{collection ? "Collection settings" : "New collection"}</h2>
        <label className="mt-5 block">
          <span className="mb-1.5 block text-sm font-medium text-ink">Name</span>
          <input required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder="HR policies"
            className="w-full rounded-md border border-rule bg-surface px-3 py-2 text-sm focus:border-signal focus:outline-none" />
        </label>
        <label className="mt-4 block">
          <span className="mb-1.5 block text-sm font-medium text-ink">Description (optional)</span>
          <input maxLength={300} value={description} onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-md border border-rule bg-surface px-3 py-2 text-sm focus:border-signal focus:outline-none" />
        </label>
        <fieldset className="mt-5">
          <legend className="text-sm font-medium text-ink">Who can see it</legend>
          <label className="mt-2 flex items-start gap-2 text-sm">
            <input type="radio" checked={!restricted} onChange={() => setRestricted(false)} className="mt-1" />
            <span>
              Everyone in the workspace
              <span className="block text-xs text-muted">A folder to keep things organised.</span>
            </span>
          </label>
          <label className="mt-2 flex items-start gap-2 text-sm">
            <input type="radio" checked={restricted} onChange={() => setRestricted(true)} className="mt-1" />
            <span>
              Only the people I choose (and admins)
              <span className="block text-xs text-muted">
                Others can't see these documents, and their answers never use them.
              </span>
            </span>
          </label>
        </fieldset>
        {restricted && (
          <div className="mt-4 max-h-56 overflow-y-auto rounded-lg border border-rule">
            {people.map((p) => (
              <label key={p.id} className="flex items-center gap-3 border-b border-rule px-3 py-2 text-sm last:border-0">
                <input type="checkbox" checked={memberIds.has(p.id)} onChange={() => toggle(p.id)} />
                <span className="flex-1 truncate text-ink">{p.email}</span>
                <span className="font-mono text-[11px] text-muted">{p.role.toLowerCase()}</span>
              </label>
            ))}
          </div>
        )}
        <div className="mt-6 flex items-center gap-2">
          {collection && (
            <Button type="button" variant="ghost" onClick={remove} className="mr-auto text-danger">
              Delete collection
            </Button>
          )}
          <Button type="button" variant="secondary" onClick={onClose} className={collection ? "" : "ml-auto"}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !name.trim()}>
            {busy ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </div>
  );
}

export default function DocumentsPage() {
  const { token, user } = useAuth();
  const notify = useToast();
  const canUpload = hasRole(user, "MEMBER");
  const isAdmin = hasRole(user, "ADMIN");
  const canRemove = (doc) => doc.uploaded_by === user?.id || isAdmin;
  const [docs, setDocs] = useState([]);
  const [collections, setCollections] = useState({ general_documents: 0, collections: [] });
  const [active, setActive] = useState(ALL);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [editing, setEditing] = useState(null); // null | "new" | collection
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [slowUpload, setSlowUpload] = useState(false);
  const [loadingSamples, setLoadingSamples] = useState(false);
  const slowUploadTimer = useRef(null);
  const fileInput = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const [d, c] = await Promise.all([api.listDocuments(token), api.listCollections(token)]);
      setDocs(d);
      setCollections(c);
    } catch (err) {
      notify(err.detail || "Couldn't load your documents.");
    } finally {
      setLoading(false);
    }
  }, [token, notify]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Ingestion runs in the background: re-check anything still processing, and
  // freshly ready documents whose summary and conflict check are still coming.
  useEffect(() => {
    const summaryPending = (d) =>
      d.status === "ready" && (!d.summary || d.conflicts == null) && Date.now() - new Date(d.created_at).getTime() < 180_000;
    const pending = docs.filter((d) => IN_PROGRESS.has(d.status) || summaryPending(d));
    if (pending.length === 0) return undefined;
    const timer = setTimeout(async () => {
      const updates = await Promise.all(pending.map((d) => api.getDocument(token, d.id).catch(() => null)));
      // A new version becoming ready retires the old one: reload the list then.
      if (updates.some((u) => u && u.status === "ready" && u.previous_version_id)) {
        refresh();
        return;
      }
      setDocs((current) => current.map((d) => updates.find((u) => u && u.id === d.id) ?? d));
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [docs, token, refresh]);

  const byId = useMemo(() => Object.fromEntries(collections.collections.map((c) => [c.id, c])), [collections]);
  const uploadTarget = active === ALL || active === GENERAL ? null : active;
  const targetName = uploadTarget ? byId[uploadTarget]?.name : "General";

  const shown = docs.filter((d) => {
    if (active === GENERAL && d.collection_id) return false;
    if (active !== ALL && active !== GENERAL && d.collection_id !== active) return false;
    if (query && !d.filename.toLowerCase().includes(query.toLowerCase()) && !(d.summary || "").toLowerCase().includes(query.toLowerCase())) return false;
    if (filter === "ready") return d.status === "ready";
    if (filter === "processing") return IN_PROGRESS.has(d.status);
    if (filter === "failed") return d.status === "failed" || d.status === "reupload_required";
    if (filter === "conflicts") return d.conflicts?.length > 0 && !d.conflicts_state;
    return true;
  });

  async function addSamples() {
    setLoadingSamples(true);
    try {
      const created = await api.loadSamples(token);
      setDocs((current) => [...created, ...current]);
      notify(`Added ${created.length} sample documents. They'll be ready in a moment.`, "info");
    } catch (err) {
      notify(err.detail || "Couldn't add the sample documents.");
    } finally {
      setLoadingSamples(false);
    }
  }

  async function handleFiles(fileList) {
    const files = Array.from(fileList).filter(Boolean);
    if (files.length === 0) return;
    setUploading(true);
    setSlowUpload(false);
    slowUploadTimer.current = setTimeout(() => setSlowUpload(true), 3000);
    for (const file of files) {
      try {
        const created = await api.uploadDocument(token, file, uploadTarget);
        setDocs((current) => [created, ...current]);
      } catch (err) {
        notify(`${file.name}: ${err.detail || "upload failed"}`);
      }
    }
    clearTimeout(slowUploadTimer.current);
    setSlowUpload(false);
    setUploading(false);
  }

  async function handleDelete(doc) {
    if (!window.confirm(`Remove ${doc.filename}? Its answers will no longer cite it.`)) return;
    try {
      await api.deleteDocument(token, doc.id);
      await refresh();
    } catch (err) {
      notify(err.detail || "Couldn't remove that document.");
    }
  }

  const chip = (key, label, count, restricted) => (
    <button
      key={key}
      type="button"
      role="tab"
      aria-selected={active === key}
      onClick={() => setActive(key)}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors ${
        active === key ? "border-ink bg-ink text-paper" : "border-rule bg-surface text-ink-soft hover:border-ink/40"
      }`}
    >
      {restricted && <Icon.Lock width={13} height={13} />}
      {label}
      {count != null && <span className={`text-xs ${active === key ? "text-paper/70" : "text-muted"}`}>{count}</span>}
    </button>
  );

  return (
    <>
      <DemoBanner />
      <main className="mx-auto max-w-5xl px-5 py-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="font-display text-3xl text-ink">Documents</h1>
            <p className="mt-1 text-sm text-muted">
              PDF, Word, Markdown and text files, searchable only inside your workspace.
            </p>
          </div>
          {isAdmin && (
            <Button variant="secondary" size="sm" onClick={() => setEditing("new")}>
              + New collection
            </Button>
          )}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-2" role="tablist" aria-label="Collections">
          {chip(ALL, "All", docs.length)}
          {chip(GENERAL, "General", collections.general_documents)}
          {collections.collections.map((c) => chip(c.id, c.name, c.documents, c.restricted))}
          {isAdmin && byId[active] && (
            <button type="button" onClick={() => setEditing(byId[active])} className="text-xs text-signal">
              Collection settings
            </button>
          )}
        </div>
        {byId[active]?.restricted && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
            <Icon.Lock width={13} height={13} /> Only members of this collection and admins can see these documents or get
            answers from them.
          </p>
        )}

        {!canUpload ? (
          <p className="mt-6 rounded-lg border border-rule bg-surface px-4 py-3 text-sm text-muted">
            You have view-only access: you can ask questions about these documents, but someone with upload rights needs to
            add or remove them.
          </p>
        ) : (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              handleFiles(e.dataTransfer.files);
            }}
            className={`mt-6 rounded-lg border border-dashed px-6 py-8 text-center transition-colors ${
              dragging ? "border-signal bg-signal-soft" : "border-rule bg-surface"
            }`}
          >
            <p className="text-sm text-ink">
              Drop files here to add them to <span className="font-medium">{targetName}</span>
            </p>
            <p className="mt-1 text-xs text-muted">PDF, Word (.docx), Markdown or .txt, up to 20 MB each</p>
            {slowUpload && uploading && (
              <p className="mt-3 text-xs text-muted">⏳ Waking up the server — this can take up to a minute on the free tier.</p>
            )}
            <Button variant="secondary" className="mt-4" disabled={uploading} onClick={() => fileInput.current?.click()}>
              {uploading ? "Uploading…" : "Choose files"}
            </Button>
            <input
              ref={fileInput}
              type="file"
              multiple
              accept=".pdf,.txt,.md,.markdown,.docx,application/pdf,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="hidden"
              onChange={(e) => {
                handleFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
        )}

        <div className="mt-6 flex flex-col gap-2 sm:flex-row">
          <label className="flex flex-1 items-center gap-2 rounded-md border border-rule bg-surface px-3">
            <Icon.Search width={16} height={16} className="text-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name or summary"
              aria-label="Search documents"
              className="min-w-0 flex-1 bg-transparent py-2 text-sm focus:outline-none"
            />
          </label>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by status"
            className="rounded-md border border-rule bg-surface px-3 py-2 text-sm">
            {FILTERS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </div>

        <section className="mt-4">
          {loading ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-16 rounded-md border border-rule bg-surface pulse-soft" />
              ))}
            </div>
          ) : docs.length === 0 ? (
            <EmptyState title="Nothing indexed yet">
              Add a handbook, a policy, or any PDF above. Once it finishes processing you can ask questions about it.
              {canUpload && (
                <span className="mt-4 block">
                  <Button variant="secondary" size="sm" disabled={loadingSamples} onClick={addSamples}>
                    {loadingSamples ? "Adding…" : "Try with sample documents"}
                  </Button>
                  <span className="mt-2 block text-xs text-muted">Five short policies from Northwind Freight, a made-up company.</span>
                </span>
              )}
            </EmptyState>
          ) : shown.length === 0 ? (
            <p className="rounded-lg border border-dashed border-rule px-4 py-8 text-center text-sm text-muted">
              No documents match. Try another collection, search or filter.
            </p>
          ) : (
            <ul className="divide-y divide-rule overflow-hidden rounded-lg border border-rule bg-surface">
              {shown.map((doc) => {
                const col = doc.collection_id ? byId[doc.collection_id] : null;
                const openConflicts = doc.conflicts?.length > 0 && !doc.conflicts_state;
                return (
                  <li key={doc.id} className="flex items-start gap-4 px-4 py-3.5">
                    <Icon.Doc className="mt-0.5 shrink-0 text-muted" width={18} height={18} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link to={`/documents/${doc.id}`} className="truncate text-sm font-medium text-ink hover:text-signal">
                          {doc.filename}
                        </Link>
                        {doc.version > 1 && (
                          <span className="rounded-sm bg-signal-soft px-1.5 py-0.5 font-mono text-[10px] text-signal">v{doc.version}</span>
                        )}
                        {col && (
                          <span className="inline-flex items-center gap-1 rounded-sm bg-rule-soft px-1.5 py-0.5 text-[11px] text-ink-soft">
                            {col.restricted && <Icon.Lock width={11} height={11} />}
                            {col.name}
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 font-mono text-[11px] text-muted">
                        {doc.status === "ready"
                          ? `${doc.num_chunks} passage${doc.num_chunks === 1 ? "" : "s"} indexed`
                          : new Date(doc.created_at).toLocaleDateString()}
                        {doc.truncated && " · only the first part was indexed (file too long)"}
                      </p>
                      {doc.summary && doc.status === "ready" && (
                        <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-ink-soft" title={doc.summary}>
                          {doc.summary}
                        </p>
                      )}
                      {openConflicts && (
                        <Link to={`/documents/${doc.id}`}
                          className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-warn-soft px-2 py-1 text-xs text-warn">
                          <Icon.Alert width={13} height={13} /> May contradict {doc.conflicts.length === 1 ? "another document" : `${doc.conflicts.length} passages`} — review
                        </Link>
                      )}
                      {doc.error && doc.status !== "ready" && (
                        <p className={`mt-1 text-xs ${IN_PROGRESS.has(doc.status) ? "text-muted" : "text-danger"}`}>{doc.error}</p>
                      )}
                    </div>
                    <StatusBadge status={doc.status} />
                    {canRemove(doc) && (
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(doc)} className="text-danger">
                        Remove
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </main>
      {editing && (
        <CollectionModal
          collection={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            setEditing(null);
            if (saved) setActive(saved.id);
            else setActive(ALL);
            refresh();
          }}
        />
      )}
    </>
  );
}
