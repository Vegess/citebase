import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { hasRole, useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, StatusBadge, useToast } from "../components/ui";
import { Icon } from "../components/icons";

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function Card({ title, action, children }) {
  return (
    <section className="rounded-xl border border-rule bg-surface p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Checklist({ checklist, canUpload, onSamples, loadingSamples, isAdmin }) {
  const steps = [
    { done: checklist.has_documents, label: "Add your first documents", to: "/documents" },
    { done: checklist.has_asked, label: "Ask a question and check the sources", to: "/chat" },
    ...(isAdmin ? [{ done: checklist.has_teammates, label: "Invite a teammate", to: "/team" }] : []),
  ];
  const finished = steps.filter((s) => s.done).length;
  if (finished === steps.length) return null;
  return (
    <section className="rounded-xl border border-signal/30 bg-signal-soft/40 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-xl text-ink">Get set up</h2>
          <p className="text-sm text-ink-soft">
            {finished} of {steps.length} done. It takes about two minutes.
          </p>
        </div>
        {canUpload && !checklist.has_documents && (
          <Button variant="secondary" size="sm" disabled={loadingSamples} onClick={onSamples}>
            <Icon.Sparkle width={16} height={16} className="mr-1.5 inline" />
            {loadingSamples ? "Adding…" : "Try with sample documents"}
          </Button>
        )}
      </div>
      <ol className="mt-4 space-y-2">
        {steps.map((s, i) => (
          <li key={s.label}>
            <Link
              to={s.to}
              className="flex items-center gap-3 rounded-lg bg-surface px-3 py-2.5 text-sm hover:bg-rule-soft"
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  s.done ? "bg-source text-white" : "border border-rule text-muted"
                }`}
              >
                {s.done ? <Icon.Check width={14} height={14} /> : i + 1}
              </span>
              <span className={s.done ? "text-muted line-through" : "text-ink"}>{s.label}</span>
              {!s.done && <Icon.Arrow width={16} height={16} className="ml-auto text-muted" />}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function HomePage() {
  const { token, user } = useAuth();
  const notify = useToast();
  const navigate = useNavigate();
  const [home, setHome] = useState(null);
  const [question, setQuestion] = useState("");
  const [loadingSamples, setLoadingSamples] = useState(false);

  const load = useCallback(async () => {
    try {
      setHome(await api.getHome(token));
    } catch (err) {
      notify(err.detail || "Couldn't load your home page.");
    }
  }, [token, notify]);

  useEffect(() => {
    load();
  }, [load]);

  // While documents are processing, check back every few seconds.
  useEffect(() => {
    if (!home?.processing) return undefined;
    const timer = setTimeout(load, 4000);
    return () => clearTimeout(timer);
  }, [home, load]);

  async function addSamples() {
    setLoadingSamples(true);
    try {
      const created = await api.loadSamples(token);
      notify(`Added ${created.length} sample documents. They'll be ready in a moment.`, "info");
      await load();
    } catch (err) {
      notify(err.detail || "Couldn't add the sample documents.");
    } finally {
      setLoadingSamples(false);
    }
  }

  function ask(e) {
    e.preventDefault();
    if (question.trim()) navigate("/chat", { state: { ask: question.trim() } });
  }

  const name = user?.email?.split("@")[0]?.split(/[._-]/)[0] || "";
  const alerts = home?.alerts;
  const alertCount = alerts ? alerts.conflicts.length + alerts.failed.length + (alerts.unanswered_questions ? 1 : 0) : 0;

  return (
    <main className="mx-auto max-w-5xl px-5 py-10">
      <p className="text-sm text-muted">{user?.org_name}</p>
      <h1 className="font-display text-3xl text-ink">
        {greeting()}
        {name && `, ${name.charAt(0).toUpperCase()}${name.slice(1)}`}
      </h1>

      <form onSubmit={ask} className="mt-6 flex gap-2 rounded-xl border border-rule bg-surface p-2 shadow-sm">
        <Icon.Search className="ml-2 mt-2.5 shrink-0 text-muted" />
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask anything about your documents…"
          aria-label="Ask a question"
          className="min-w-0 flex-1 bg-transparent px-1 text-[15px] text-ink placeholder:text-muted focus:outline-none"
        />
        <Button type="submit" disabled={!question.trim()}>
          Ask
        </Button>
      </form>

      {!home ? (
        <div className="mt-8 grid gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-40 rounded-xl border border-rule bg-surface pulse-soft" />
          ))}
        </div>
      ) : (
        <div className="mt-8 space-y-4">
          <Checklist
            checklist={home.checklist}
            isAdmin={home.is_admin}
            canUpload={hasRole(user, "MEMBER")}
            onSamples={addSamples}
            loadingSamples={loadingSamples}
          />

          <div className="grid grid-cols-3 gap-2 sm:gap-4">
            {[
              ["Documents ready", home.documents_ready, `${home.documents_total} in total`],
              ["Processing", home.processing, home.processing ? "Updating automatically" : "Nothing waiting"],
              ["Needs attention", alertCount, alertCount ? "See below" : "All clear"],
            ].map(([label, n, sub]) => (
              <div key={label} className="rounded-xl border border-rule bg-surface p-3 sm:p-5">
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted sm:text-xs">{label}</p>
                <p className="mt-1 font-display text-2xl text-ink sm:text-3xl">{n}</p>
                <p className="hidden text-xs text-muted sm:block">{sub}</p>
              </div>
            ))}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Card
              title="Recent documents"
              action={
                <Link to="/documents" className="text-xs font-medium text-signal">
                  All documents
                </Link>
              }
            >
              {home.recent_documents.length === 0 ? (
                <p className="text-sm text-muted">Nothing uploaded yet.</p>
              ) : (
                <ul className="space-y-3">
                  {home.recent_documents.map((d) => (
                    <li key={d.id} className="flex items-start gap-3">
                      <Icon.Doc className="mt-0.5 shrink-0 text-muted" width={18} height={18} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-ink">{d.filename}</p>
                        {d.summary && <p className="line-clamp-2 text-xs text-muted">{d.summary}</p>}
                      </div>
                      <StatusBadge status={d.status} />
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Needs attention">
              {alertCount === 0 ? (
                <p className="flex items-center gap-2 text-sm text-muted">
                  <Icon.Check width={16} height={16} className="text-source" /> No conflicts or failed uploads.
                </p>
              ) : (
                <ul className="space-y-2.5 text-sm">
                  {alerts.conflicts.map((f) => (
                    <li key={`c-${f}`} className="flex gap-2">
                      <Icon.Alert width={16} height={16} className="mt-0.5 shrink-0 text-warn" />
                      <span>
                        <span className="font-medium text-ink">{f}</span>{" "}
                        <span className="text-muted">may contradict another document.</span>{" "}
                        <Link to="/documents" className="text-signal">
                          Review
                        </Link>
                      </span>
                    </li>
                  ))}
                  {alerts.failed.map((f) => (
                    <li key={`f-${f}`} className="flex gap-2">
                      <Icon.Alert width={16} height={16} className="mt-0.5 shrink-0 text-danger" />
                      <span>
                        <span className="font-medium text-ink">{f}</span>{" "}
                        <span className="text-muted">couldn't be processed. Upload it again.</span>
                      </span>
                    </li>
                  ))}
                  {alerts.unanswered_questions > 0 && (
                    <li className="flex gap-2">
                      <Icon.Search width={16} height={16} className="mt-0.5 shrink-0 text-signal" />
                      <span>
                        <span className="font-medium text-ink">{alerts.unanswered_questions}</span>{" "}
                        <span className="text-muted">question(s) this week had no answer in your documents.</span>{" "}
                        <Link to="/insights" className="text-signal">
                          See gaps
                        </Link>
                      </span>
                    </li>
                  )}
                </ul>
              )}
            </Card>
          </div>

          {home.is_admin && (
            <Card
              title="What your team asked this week"
              action={
                <Link to="/insights" className="text-xs font-medium text-signal">
                  Insights
                </Link>
              }
            >
              {home.popular_questions.length === 0 ? (
                <p className="text-sm text-muted">No questions yet this week.</p>
              ) : (
                <ul className="divide-y divide-rule">
                  {home.popular_questions.map((q) => (
                    <li key={q.question} className="flex items-center gap-3 py-2 text-sm">
                      <button
                        type="button"
                        className="min-w-0 flex-1 truncate text-left text-ink hover:text-signal"
                        onClick={() => navigate("/chat", { state: { ask: q.question } })}
                      >
                        {q.question}
                      </button>
                      <span className="font-mono text-xs text-muted">×{q.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </div>
      )}
    </main>
  );
}
