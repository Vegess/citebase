import { useCallback, useEffect, useRef, useState } from "react";
import { hasRole, useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, EmptyState, IN_PROGRESS, StatusBadge, useToast } from "../components/ui";
import { DemoBanner } from "../components/DemoBanner";

const POLL_MS = 2000;

export default function DocumentsPage() {
  const { token, user } = useAuth();
  const notify = useToast();
  const canUpload = hasRole(user, "MEMBER");
  const canRemove = (doc) => doc.uploaded_by === user?.id || hasRole(user, "ADMIN");
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [slowUpload, setSlowUpload] = useState(false);
  const slowUploadTimer = useRef(null);
  const fileInput = useRef(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocuments(token));
    } catch (err) {
      notify(err.detail || "Couldn't load your documents.");
    } finally {
      setLoading(false);
    }
  }, [token, notify]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Ingestion runs in the background, so anything still processing is
  // re-checked until the backend marks it ready or failed.
  useEffect(() => {
    // Also re-check freshly ready documents for a minute or two: their summary
    // is written by a follow-up job shortly after they become ready.
    const summaryPending = (d) =>
      d.status === "ready" && !d.summary && Date.now() - new Date(d.created_at).getTime() < 120_000;
    const pending = docs.filter((d) => IN_PROGRESS.has(d.status) || summaryPending(d));
    if (pending.length === 0) return;

    const timer = setTimeout(async () => {
      const updates = await Promise.all(
        pending.map((d) => api.getDocument(token, d.id).catch(() => null)),
      );
      setDocs((current) =>
        current.map((d) => updates.find((u) => u && u.id === d.id) ?? d),
      );
    }, POLL_MS);

    return () => clearTimeout(timer);
  }, [docs, token]);

  async function handleFiles(fileList) {
    const files = Array.from(fileList).filter(Boolean);
    if (files.length === 0) return;

    setUploading(true);
    setSlowUpload(false);
    
    // Show slow upload message after 3 seconds
    slowUploadTimer.current = setTimeout(() => {
      setSlowUpload(true);
    }, 3000);

    for (const file of files) {
      try {
        const created = await api.uploadDocument(token, file);
        setDocs((current) => [created, ...current]);
      } catch (err) {
        notify(`${file.name}: ${err.detail || "upload failed"}`);
      }
    }
    
    if (slowUploadTimer.current) {
      clearTimeout(slowUploadTimer.current);
      slowUploadTimer.current = null;
    }
    setSlowUpload(false);
    setUploading(false);
  }

  async function handleDelete(doc) {
    if (!confirm(`Remove ${doc.filename}? Its answers will no longer cite it.`)) return;
    try {
      await api.deleteDocument(token, doc.id);
      setDocs((current) => current.filter((d) => d.id !== doc.id));
    } catch (err) {
      notify(err.detail || "Couldn't remove that document.");
    }
  }

  return (
    <>
      <DemoBanner />
      <main className="mx-auto max-w-4xl px-5 py-10">
      <h1 className="font-display text-3xl text-ink">Documents</h1>
      <p className="mt-1 text-sm text-muted">
        PDFs and text files. Each one is read, indexed, and made searchable for your
        organisation only. Scanned PDFs (images of pages) aren't supported yet.
      </p>

      {!canUpload && (
        <p className="mt-7 rounded-lg border border-rule bg-surface px-4 py-3 text-sm text-muted">
          You have view-only access: you can ask questions about these documents, but an
          admin needs to upload or remove them.
        </p>
      )}
      {canUpload && (
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
        className={`mt-7 rounded-lg border border-dashed px-6 py-10 text-center transition-colors ${
          dragging ? "border-signal bg-signal-soft" : "border-rule bg-surface"
        }`}
      >
        <p className="text-sm text-ink">Drop files here to add them</p>
        <p className="mt-1 text-xs text-muted">PDF or .txt, up to 20 MB each</p>
        {slowUpload && uploading && (
          <p className="mt-3 text-xs text-muted">
            ⏳ Waking up the server — this can take up to a minute on the free tier.
          </p>
        )}
        <Button
          variant="secondary"
          className="mt-4"
          disabled={uploading}
          onClick={() => fileInput.current?.click()}
        >
          {uploading ? "Uploading…" : "Choose files"}
        </Button>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept=".pdf,.txt,application/pdf,text/plain"
          className="hidden"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      )}

      <section className="mt-8">
        {loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-16 rounded-md border border-rule bg-surface pulse-soft" />
            ))}
          </div>
        ) : docs.length === 0 ? (
          <EmptyState title="Nothing indexed yet">
            Add a handbook, a policy, or any PDF above. Once it finishes processing you
            can ask questions about it.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-rule overflow-hidden rounded-lg border border-rule bg-surface">
            {docs.map((doc) => (
              <li key={doc.id} className="flex items-center gap-4 px-4 py-3.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-ink">{doc.filename}</p>
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
                  {doc.error && doc.status !== "ready" && (
                    <p className={`mt-1 text-xs ${IN_PROGRESS.has(doc.status) ? "text-muted" : "text-danger"}`}>
                      {doc.error}
                    </p>
                  )}
                </div>
                <StatusBadge status={doc.status} />
                {canRemove(doc) && (
                  <Button variant="danger" onClick={() => handleDelete(doc)}>
                    Remove
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
    </>
  );
}
