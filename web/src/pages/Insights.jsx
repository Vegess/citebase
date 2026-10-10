import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, EmptyState, LoadError, useToast } from "../components/ui";

const RANGES = [7, 30, 90];

function StatTile({ label, value, hint }) {
  return (
    <div className="rounded-lg border border-rule bg-surface p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 font-display text-3xl text-ink">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

/** Single-series daily bars: one hue, no legend (the title names the series). */
function DailyBars({ days }) {
  const max = Math.max(1, ...days.map((d) => d.questions));
  return (
    <figure className="rounded-lg border border-rule bg-surface p-4">
      <figcaption className="mb-3 text-sm font-medium text-ink">Questions per day</figcaption>
      <div className="flex h-28 items-end gap-[2px]" role="img" aria-label="Questions asked per day">
        {days.map((d) => (
          <div key={d.date} className="group relative flex h-full flex-1 items-end">
            <div
              className="w-full rounded-t-[4px] bg-signal/80 transition-colors group-hover:bg-signal"
              style={{ height: `${d.questions ? Math.max(4, (d.questions / max) * 100) : 0}%` }}
            />
            <span className="pointer-events-none absolute -top-7 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded-sm bg-ink px-1.5 py-0.5 font-mono text-[10px] text-paper group-hover:block">
              {d.date.slice(5)} · {d.questions}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between font-mono text-[10px] text-muted">
        <span>{days[0]?.date.slice(5)}</span>
        <span>{days[days.length - 1]?.date.slice(5)}</span>
      </div>
      <table className="sr-only">
        <caption>Questions per day</caption>
        <tbody>
          {days.map((d) => (
            <tr key={d.date}><td>{d.date}</td><td>{d.questions}</td></tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

function Section({ title, hint, children }) {
  return (
    <section className="rounded-lg border border-rule bg-surface p-5">
      <h2 className="font-display text-xl text-ink">{title}</h2>
      {hint && <p className="mt-0.5 mb-3 text-sm text-muted">{hint}</p>}
      {children}
    </section>
  );
}

export default function InsightsPage() {
  const { token } = useAuth();
  const notify = useToast();
  const navigate = useNavigate();
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setData(null);
    setFailed(false);
    api.getInsights(token, days).then(setData).catch(() => setFailed(true));
  }, [token, days, attempt]);

  const reload = () => api.getInsights(token, days).then(setData).catch(() => {});
  async function review(id, state) {
    try {
      await api.reviewConflicts(token, id, state);
      reload();
    } catch (err) {
      notify(err.detail || "Couldn't update that conflict.");
    }
  }
  async function unverify(id) {
    if (!window.confirm("Stop reusing this answer? New questions will get a freshly written answer.")) return;
    try {
      await api.removeVerified(token, id);
      reload();
    } catch (err) {
      notify(err.detail || "Couldn't remove it.");
    }
  }

  const t = data?.totals;
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);

  return (
    <main className="mx-auto max-w-5xl px-5 py-10">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl text-ink">Insights</h1>
          <p className="mt-1 text-sm text-muted">
            What your team asks, and what your documents can't answer yet. Questions are shown without who asked them.
          </p>
        </div>
        <div className="flex rounded-md border border-rule bg-surface p-0.5" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setDays(r)}
              aria-pressed={days === r}
              className={`rounded px-3 py-1 text-xs ${days === r ? "bg-ink text-paper" : "text-ink-soft hover:text-ink"}`}
            >
              {r} days
            </button>
          ))}
        </div>
      </div>

      {!data && failed ? (
        <div className="mt-8">
          <LoadError onRetry={() => setAttempt((n) => n + 1)} />
        </div>
      ) : !data ? (
        <div className="mt-8 grid gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-24 rounded-lg border border-rule bg-surface pulse-soft" />)}
        </div>
      ) : t.questions === 0 ? (
        <div className="mt-8">
          <EmptyState title="No questions yet">
            Once your team starts asking, you'll see what they look for and where your documents fall short.
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Questions" value={t.questions} hint={`last ${data.days} days`} />
            <StatTile label="Answered from your documents" value={pct(t.answer_rate)} hint={`${t.answered} of ${t.questions}`} />
            <StatTile label="Not in your documents" value={t.not_in_documents} hint="see knowledge gaps below" />
            <StatTile label="Feedback" value={`👍 ${t.helpful} · 👎 ${t.not_helpful}`} hint={t.degraded ? `${t.degraded} degraded answers` : "from your team"} />
          </div>

          <div className="mt-4">
            <DailyBars days={data.daily} />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Section title="Knowledge gaps" hint="Asked, but your documents don't cover them. Upload something that does.">
              {data.knowledge_gaps.length === 0 ? (
                <p className="text-sm text-muted">None — every question found an answer.</p>
              ) : (
                <ul className="divide-y divide-rule">
                  {data.knowledge_gaps.map((g) => (
                    <li key={g.question} className="flex items-start justify-between gap-3 py-2.5">
                      <span className="text-sm text-ink">{g.question}</span>
                      <span className="flex shrink-0 items-center gap-2">
                        <span className="rounded-sm bg-warn-soft px-1.5 py-0.5 font-mono text-[11px] text-warn">×{g.count}</span>
                        <Link to="/documents" className="text-xs font-medium text-signal">Add a document</Link>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title="Most asked" hint="Click one to ask it yourself.">
              <ul className="divide-y divide-rule">
                {data.top_questions.map((q) => (
                  <li key={q.question} className="flex items-start justify-between gap-3 py-2.5">
                    <button
                      type="button"
                      className="text-left text-sm text-ink hover:text-signal"
                      onClick={() => navigate("/chat", { state: { ask: q.question } })}
                    >
                      {q.question}
                    </button>
                    <span className="shrink-0 font-mono text-[11px] text-muted">×{q.count}</span>
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="Documents doing the work" hint="How many answers cited each file.">
              {data.top_documents.length === 0 ? (
                <p className="text-sm text-muted">No answers have cited a document yet.</p>
              ) : (
                <ul className="space-y-2">
                  {data.top_documents.map((d) => (
                    <li key={d.filename}>
                      <div className="flex justify-between text-sm">
                        <span className="truncate text-ink">{d.filename}</span>
                        <span className="font-mono text-[11px] text-muted">{d.answers}</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-rule-soft">
                        <div
                          className="h-1.5 rounded-full bg-source"
                          style={{ width: `${(d.answers / data.top_documents[0].answers) * 100}%` }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title="Marked not helpful" hint="Worth a look: a missing document or an unclear policy.">
              {data.unhelpful_answers.length === 0 ? (
                <p className="text-sm text-muted">No 👎 yet.</p>
              ) : (
                <ul className="divide-y divide-rule">
                  {data.unhelpful_answers.map((a) => (
                    <li key={`${a.created_at}-${a.question}`} className="py-2.5">
                      <p className="text-sm text-ink">{a.question}</p>
                      <p className="mt-0.5 line-clamp-2 text-xs text-muted">{a.answer}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
        </>
      )}

      {data && (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Section title="Conflict inbox" hint="Documents that may contradict each other. Fix the files, then mark them resolved.">
            {data.open_conflicts.length === 0 ? (
              <p className="text-sm text-muted">Nothing to review.</p>
            ) : (
              <ul className="divide-y divide-rule">
                {data.open_conflicts.map((d) => (
                  <li key={d.id} className="py-2.5">
                    <div className="flex items-center gap-2">
                      <Link to={`/documents/${d.id}`} className="min-w-0 flex-1 truncate text-sm font-medium text-ink hover:text-signal">
                        {d.filename}
                      </Link>
                      <Button size="sm" variant="secondary" onClick={() => review(d.id, "resolved")}>Resolved</Button>
                      <Button size="sm" variant="ghost" onClick={() => review(d.id, "ignored")}>Ignore</Button>
                    </div>
                    {d.conflicts.slice(0, 2).map((c, i) => (
                      <p key={i} className="mt-1 text-xs text-muted">
                        <span className="font-medium text-warn">{c.topic}:</span> “{c.this_says}” vs “{c.other_says}” in{" "}
                        <span className="font-mono">{c.other_file}</span>
                      </p>
                    ))}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Verified answers" hint="Approved answers reused instantly for the same question. Mark one from any answer in Ask.">
            {data.verified_answers.length === 0 ? (
              <p className="text-sm text-muted">None yet. Under a good answer, click “Mark as verified”.</p>
            ) : (
              <ul className="divide-y divide-rule">
                {data.verified_answers.map((v) => (
                  <li key={v.id} className="flex items-start gap-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink">{v.question}</p>
                      <p className="mt-0.5 text-xs text-muted">
                        {v.by ? `by ${v.by}` : ""} · {new Date(v.at).toLocaleDateString()}
                        {!v.current && <span className="ml-1 text-warn">· paused: a cited document changed</span>}
                      </p>
                    </div>
                    <Button size="sm" variant="ghost" onClick={() => unverify(v.id)}>Remove</Button>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {data.stale_documents.length > 0 && (
            <Section title="Possibly out of date" hint="Not updated in over a year. Upload a new version if the policy changed.">
              <ul className="divide-y divide-rule">
                {data.stale_documents.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                    <Link to={`/documents/${d.id}`} className="truncate text-ink hover:text-signal">{d.filename}</Link>
                    <span className="shrink-0 text-xs text-muted">{new Date(d.updated_at).toLocaleDateString()}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>
      )}
    </main>
  );
}
