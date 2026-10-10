import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { hasRole, useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, IN_PROGRESS, StatusBadge, useToast } from "../components/ui";
import { Icon } from "../components/icons";

const EVENT_LABEL = {
  queued: "Queued for processing",
  chunking: "Reading the text",
  embedding: "Building the search index",
  ready: "Ready to answer questions",
  failed: "Processing failed",
  superseded: "Replaced by a newer version",
  reupload_required: "Needs to be uploaded again",
};

const when = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

function Panel({ title, children, action }) {
  return (
    <section className="rounded-xl border border-rule bg-surface p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export default function DocumentDetailPage() {
  const { id } = useParams();
  const { token, user } = useAuth();
  const notify = useToast();
  const navigate = useNavigate();
  const [detail, setDetail] = useState(null);
  const [missing, setMissing] = useState(false);
  const [collections, setCollections] = useState([]);
  const [busy, setBusy] = useState(false);
  const versionInput = useRef(null);
  const isAdmin = hasRole(user, "ADMIN");

  const load = useCallback(async () => {
    try {
      const [d, c] = await Promise.all([api.getDocumentDetail(token, id), api.listCollections(token)]);
      setDetail(d);
      setCollections(c.collections);
    } catch (err) {
      if (err.status === 404) setMissing(true);
      else notify(err.detail || "Couldn't load this document.");
    }
  }, [token, id, notify]);

  useEffect(() => {
    setDetail(null);
    setMissing(false);
    load();
  }, [load]);

  // Keep refreshing while this file or a newer version is still processing.
  useEffect(() => {
    if (!detail) return undefined;
    const working = IN_PROGRESS.has(detail.document.status) || detail.versions.some((v) => IN_PROGRESS.has(v.status));
    if (!working) return undefined;
    const t = setTimeout(load, 2500);
    return () => clearTimeout(t);
  }, [detail, load]);

  if (missing) {
    return (
      <main className="mx-auto max-w-3xl px-5 py-16 text-center">
        <p className="font-display text-2xl text-ink">Document not found</p>
        <p className="mt-2 text-sm text-muted">It may have been removed, or it's in a collection you can't see.</p>
        <Link to="/documents" className="mt-4 inline-block text-sm text-signal">
          Back to documents
        </Link>
      </main>
    );
  }
  if (!detail) {
    return (
      <main className="mx-auto max-w-5xl space-y-4 px-5 py-10">
        <div className="h-10 w-2/3 rounded bg-rule-soft pulse-soft" />
        <div className="h-40 rounded-xl border border-rule bg-surface pulse-soft" />
      </main>
    );
  }

  const doc = detail.document;
  const latest = detail.versions[detail.versions.length - 1];
  const isOld = doc.status === "superseded";
  const openConflicts = doc.conflicts?.length > 0 && !doc.conflicts_state;

  async function newVersion(file) {
    if (!file) return;
    setBusy(true);
    try {
      const created = await api.uploadVersion(token, doc.id, file);
      notify(`Version ${created.version} uploaded. It replaces this one as soon as it's ready.`, "info");
      navigate(`/documents/${created.id}`);
    } catch (err) {
      notify(err.detail || "Couldn't upload the new version.");
    } finally {
      setBusy(false);
    }
  }

  async function move(collectionId) {
    try {
      await api.moveDocument(token, doc.id, collectionId);
      notify("Moved.", "info");
      load();
    } catch (err) {
      notify(err.detail || "Couldn't move this document.");
    }
  }

  async function review(state) {
    try {
      await api.reviewConflicts(token, doc.id, state);
      load();
    } catch (err) {
      notify(err.detail || "Couldn't update the review.");
    }
  }

  async function remove() {
    const msg = doc.version > 1 && !isOld
      ? `Remove version ${doc.version}? Version ${doc.version - 1} will answer questions again.`
      : `Remove ${doc.filename}? Its answers will no longer cite it.`;
    if (!window.confirm(msg)) return;
    try {
      await api.deleteDocument(token, doc.id);
      navigate("/documents");
    } catch (err) {
      notify(err.detail || "Couldn't remove this document.");
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-5 py-10">
      <Link to="/documents" className="text-sm text-muted hover:text-ink">
        ← Documents
      </Link>
      <div className="mt-3 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="break-words font-display text-3xl text-ink">{doc.filename}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
            <span>Version {doc.version}</span>
            <span>·</span>
            <span>
              {detail.collection ? (
                <span className="inline-flex items-center gap-1">
                  {detail.collection.restricted && <Icon.Lock width={13} height={13} />}
                  {detail.collection.name}
                </span>
              ) : (
                "General"
              )}
            </span>
            <span>·</span>
            <span>
              Added by {detail.uploaded_by_email || "a former member"} on {new Date(doc.created_at).toLocaleDateString()}
            </span>
          </p>
        </div>
        <StatusBadge status={doc.status} />
      </div>

      {isOld && latest && latest.id !== doc.id && (
        <p className="mt-4 rounded-lg bg-warn-soft px-4 py-3 text-sm text-warn">
          This is an older version and is no longer used for answers.{" "}
          <Link to={`/documents/${latest.id}`} className="font-medium underline">
            Open version {latest.version}
          </Link>
        </p>
      )}

      {doc.status === "ready" && (
        <div className="mt-5 flex flex-wrap gap-2">
          <Button onClick={() => navigate("/chat", { state: { ask: `Summarise ${doc.filename}` } })}>
            <Icon.Chat width={16} height={16} className="mr-1.5 inline" /> Summarise it
          </Button>
          {detail.can_manage && (
            <>
              <Button variant="secondary" disabled={busy} onClick={() => versionInput.current?.click()}>
                <Icon.Upload width={16} height={16} className="mr-1.5 inline" /> {busy ? "Uploading…" : "Upload new version"}
              </Button>
              <input ref={versionInput} type="file" className="hidden"
                accept=".pdf,.txt,.md,.markdown,.docx" onChange={(e) => { newVersion(e.target.files[0]); e.target.value = ""; }} />
            </>
          )}
        </div>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="space-y-4">
          <Panel title="Summary">
            {doc.summary ? (
              <p className="text-sm leading-relaxed text-ink-soft">{doc.summary}</p>
            ) : (
              <p className="text-sm text-muted">{doc.status === "ready" ? "Being written…" : "Available once the document is ready."}</p>
            )}
          </Panel>

          {doc.suggested_questions?.length > 0 && (
            <Panel title="Questions this document answers">
              <div className="flex flex-wrap gap-2">
                {doc.suggested_questions.map((q) => (
                  <button key={q} type="button" onClick={() => navigate("/chat", { state: { ask: q } })}
                    className="rounded-full border border-rule px-3 py-1.5 text-left text-sm text-ink hover:border-signal hover:text-signal">
                    {q}
                  </button>
                ))}
              </div>
            </Panel>
          )}

          {doc.conflicts?.length > 0 && (
            <Panel
              title={openConflicts ? "Possible conflicts" : `Possible conflicts (${doc.conflicts_state})`}
              action={
                isAdmin &&
                (openConflicts ? (
                  <span className="flex gap-1">
                    <Button size="sm" variant="secondary" onClick={() => review("resolved")}>Mark resolved</Button>
                    <Button size="sm" variant="ghost" onClick={() => review("ignored")}>Ignore</Button>
                  </span>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => review(null)}>Reopen</Button>
                ))
              }
            >
              <ul className="space-y-2 text-sm">
                {doc.conflicts.map((c, i) => (
                  <li key={i} className={`rounded-md px-3 py-2 ${openConflicts ? "bg-warn-soft" : "bg-rule-soft"}`}>
                    <p className="font-medium text-ink">{c.topic}</p>
                    <p className="text-ink-soft">
                      This file says “{c.this_says}”, but <span className="font-mono text-xs">{c.other_file}</span> says “{c.other_says}”.
                    </p>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>

        <div className="space-y-4">
          {detail.can_manage && !isOld && (
            <Panel title="Collection">
              <select value={detail.collection?.id || ""} onChange={(e) => move(e.target.value)}
                aria-label="Move to collection" className="w-full rounded-md border border-rule bg-surface px-3 py-2 text-sm">
                <option value="">General (everyone)</option>
                {collections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {c.restricted ? " (restricted)" : ""}
                  </option>
                ))}
              </select>
            </Panel>
          )}

          <Panel title="Versions">
            <ol className="space-y-2">
              {[...detail.versions].reverse().map((v) => (
                <li key={v.id} className="flex items-center gap-2 text-sm">
                  <span className="w-8 font-mono text-xs text-muted">v{v.version}</span>
                  {v.id === doc.id ? (
                    <span className="min-w-0 flex-1 truncate font-medium text-ink">{v.filename}</span>
                  ) : (
                    <Link to={`/documents/${v.id}`} className="min-w-0 flex-1 truncate text-signal">{v.filename}</Link>
                  )}
                  <StatusBadge status={v.status} />
                </li>
              ))}
            </ol>
          </Panel>

          <Panel title="History">
            <ol className="relative space-y-3 border-l border-rule pl-4">
              {detail.events.map((e) => (
                <li key={e.id} className="relative text-sm">
                  <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-rule" />
                  <p className="text-ink">{EVENT_LABEL[e.to_status] ?? e.to_status}</p>
                  <p className="text-xs text-muted">
                    {when(e.created_at)}
                    {e.detail ? ` · ${e.detail}` : ""}
                  </p>
                </li>
              ))}
            </ol>
          </Panel>

          {detail.can_manage && (
            <Button variant="ghost" className="w-full text-danger" onClick={remove}>
              Remove this {doc.version > 1 ? "version" : "document"}
            </Button>
          )}
        </div>
      </div>
    </main>
  );
}
