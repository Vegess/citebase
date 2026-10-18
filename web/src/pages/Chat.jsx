import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { hasRole, useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, EmptyState, useToast } from "../components/ui";
import { Icon } from "../components/icons";
import { useConversationState } from "../hooks/useConversationState";
import { useDialog } from "../hooks/useDialog";

/**
 * Sources are the point of the product: an answer you cannot trace is an
 * answer you cannot use. They get their own colour and the document's own
 * vocabulary — filename, chunk index — rather than being tucked away.
 */
function Sources({ citations, onOpen }) {
  if (!citations?.length) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {citations.map((c, i) => (
        <button
          type="button"
          key={`${c.filename}-${c.chunk_index}-${i}`}
          onClick={() => onOpen?.(c)}
          title="Show the passage this came from"
          className="inline-flex items-center gap-1.5 rounded-sm border border-source/20 bg-source-soft px-2 py-1 font-mono text-[11px] text-source transition-colors hover:border-source/50 hover:bg-source/15"
        >
          <span className="opacity-60">{c.n ?? i + 1}</span>
          <span className="max-w-[220px] truncate">{c.filename}</span>
          <span className="opacity-60">#{c.chunk_index}</span>
        </button>
      ))}
    </div>
  );
}

const STOP = new Set(["the", "and", "for", "what", "when", "how", "does", "with", "are", "our", "you", "your", "can", "this", "that", "from", "have", "who", "which", "about", "into", "there"]);

/** Highlight the question's words in the passage, so the reader sees why it matched. */
function highlight(text, question) {
  const words = Array.from(new Set((question || "").toLowerCase().match(/[a-z0-9]{3,}/g) || [])).filter((w) => !STOP.has(w));
  if (!words.length) return text;
  const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(pattern).map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="rounded-sm bg-warn-soft px-0.5 text-ink">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

/** Side panel with the exact text behind a citation. */
function PassagePanel({ citation, question, onClose }) {
  const { token } = useAuth();
  const [passage, setPassage] = useState(null);
  const [error, setError] = useState("");
  const [context, setContext] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setPassage(null);
    setError("");
    setContext(false);
    api
      .getPassage(token, { docId: citation.doc_id, filename: citation.filename, chunkIndex: citation.chunk_index })
      .then((p) => !cancelled && setPassage(p))
      .catch((err) => !cancelled && setError(err.detail || "Couldn't load this passage."));
    return () => {
      cancelled = true;
    };
  }, [token, citation]);

  const dialog = useDialog(onClose);

  return (
    <div ref={dialog} className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Source passage">
      <div className="absolute inset-0 bg-ink/30" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-lg flex-col bg-surface shadow-2xl">
        <header className="flex items-start gap-3 border-b border-rule px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Source [{citation.n}]</p>
            <p className="truncate font-mono text-sm text-ink">{citation.filename}</p>
            {passage && (
              <p className="text-xs text-muted">
                Passage {passage.chunk_index + 1} of {passage.num_chunks || "?"}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1 text-muted hover:bg-rule-soft">
            <Icon.Close />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-5 text-[15px] leading-relaxed text-ink">
          {error ? (
            <p className="text-sm text-danger">{error}</p>
          ) : !passage ? (
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-4 rounded bg-rule-soft pulse-soft" />
              ))}
            </div>
          ) : (
            <>
              {context && passage.before && (
                <p className="mb-4 whitespace-pre-wrap text-sm text-muted">{passage.before}</p>
              )}
              <div className="whitespace-pre-wrap rounded-md border-l-4 border-source bg-source-soft/40 px-4 py-3">
                {highlight(passage.text, question)}
              </div>
              {context && passage.after && (
                <p className="mt-4 whitespace-pre-wrap text-sm text-muted">{passage.after}</p>
              )}
              {(passage.before || passage.after) && (
                <button type="button" onClick={() => setContext((v) => !v)} className="mt-4 text-sm text-signal">
                  {context ? "Hide surrounding text" : "Show surrounding text"}
                </button>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

/**
 * Answers are Markdown. Raw HTML is never rendered (react-markdown escapes it
 * by default), so a document cannot inject markup through an answer.
 */
// Models often put "<br>" inside table cells to start a new line. Raw HTML is
// never rendered, so turn just that tag into a real line break and nothing else.
const BR_TAG = /<br\s*\/?>/gi;

function withLineBreaks(children) {
  const convert = (child, key) => {
    if (typeof child !== "string" || !BR_TAG.test(child)) return child;
    BR_TAG.lastIndex = 0;
    return child.split(BR_TAG).flatMap((part, i) => (i === 0 ? [part] : [<br key={`${key}-${i}`} />, part]));
  };
  return Array.isArray(children) ? children.flatMap((c, i) => convert(c, i)) : convert(children, 0);
}

const markdownComponents = {
  p: ({ node, children, ...props }) => (
    <p className="my-2 first:mt-0 last:mb-0" {...props}>{withLineBreaks(children)}</p>
  ),
  ul: (props) => <ul className="my-2 list-disc space-y-1 pl-5" {...props} />,
  ol: (props) => <ol className="my-2 list-decimal space-y-1 pl-5" {...props} />,
  h1: (props) => <h3 className="mt-4 mb-1 font-display text-lg" {...props} />,
  h2: (props) => <h3 className="mt-4 mb-1 font-display text-lg" {...props} />,
  h3: (props) => <h4 className="mt-3 mb-1 font-semibold" {...props} />,
  strong: (props) => <strong className="font-semibold text-ink" {...props} />,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-signal underline">
      {children}
    </a>
  ),
  code: (props) => <code className="rounded-sm bg-rule-soft px-1 font-mono text-[13px]" {...props} />,
  table: (props) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm" {...props} />
    </div>
  ),
  th: (props) => <th className="border border-rule bg-rule-soft px-2 py-1 text-left font-semibold" {...props} />,
  td: ({ node, children, ...props }) => (
    <td className="border border-rule px-2 py-1 align-top" {...props}>{withLineBreaks(children)}</td>
  ),
  li: ({ node, children, ...props }) => <li {...props}>{withLineBreaks(children)}</li>,
};

// Same rule as app/services/citations.py: models sometimes write 【1】, ［1］,
// [^1], [source 1] or ranges like 【4-6】; show them all as [1] / [4, 5, 6] so
// they match the source chips. Ranges over 10 numbers are left as written.
const CITATION_VARIANT =
  /[\[【［〔]\s*(?:\^|source\s*)?(\d{1,2}(?:\s*[-–—]\s*\d{1,2})?(?:\s*[,，、]\s*\d{1,2}(?:\s*[-–—]\s*\d{1,2})?)*)(?:\s*†[^\]】］〕]*)?\s*[\]】］〕]/gi;
const MAX_RANGE = 10;

function expandCitation(match, numbers) {
  const out = [];
  for (const part of numbers.split(/\s*[,，、]\s*/)) {
    const [low, high = low] = part.split(/\s*[-–—]\s*/).map(Number);
    if (low > high || high - low + 1 > MAX_RANGE) return match;
    for (let n = low; n <= high; n += 1) if (!out.includes(n)) out.push(n);
  }
  return `[${out.join(", ")}]`;
}

// Adjacent markers ("[3][3]", "[1] [2]") collapse into one, as on the server.
const MARKER_RUN = /\[\d{1,2}(?:, \d{1,2})*\](?:\s*,?\s*\[\d{1,2}(?:, \d{1,2})*\])+(?!\()/g;

function normalizeMarkers(text) {
  const canonical = (text || "").replace(CITATION_VARIANT, expandCitation);
  return canonical.replace(MARKER_RUN, (run) => {
    const numbers = [...new Set(run.match(/\d{1,2}/g).map(Number))].sort((a, b) => a - b);
    return `[${numbers.join(", ")}]`;
  });
}

function Answer({ content }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {normalizeMarkers(content)}
    </ReactMarkdown>
  );
}

function describeStep(step) {
  if (step.action === "search") {
    const where = step.filename ? ` in ${step.filename}` : "";
    const files = step.files?.length ? ` → ${step.files.join(", ")}` : "";
    return `Searched “${step.query}”${where}${files}`;
  }
  if (step.action === "read") return `Read ${step.filename}`;
  return "Had enough to answer";
}

function ResearchSteps({ steps, live }) {
  const [open, setOpen] = useState(false);
  if (!steps?.length) return null;
  const show = live || open;
  return (
    <div className="mb-3 rounded-md border border-rule bg-surface px-3 py-2 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left font-medium text-ink-soft"
        aria-expanded={show}
      >
        <span>
          {live ? "Researching across your documents…" : `Researched in ${steps.length} step${steps.length === 1 ? "" : "s"}`}
        </span>
        {!live && <span className="text-muted">{open ? "Hide" : "Show"}</span>}
      </button>
      {show && (
        <ol className="mt-2 space-y-1.5">
          {steps.map((step) => (
            <li key={step.step} className="flex gap-2">
              <span className="font-mono text-muted">{step.step}.</span>
              <span className="text-ink">
                {describeStep(step)}
                {step.thought && <span className="block text-muted">{step.thought}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Feedback({ message, onRate, onVerify }) {
  if (!message.id || message.streaming || message.quota) return null;
  const verifiable =
    onVerify && message.answer_kind === "answered" && message.citations?.length > 0 &&
    message.citations.every((c) => c.doc_id);
  const button = (value, label, glyph) => (
    <button
      type="button"
      aria-label={label}
      aria-pressed={message.feedback === value}
      title={label}
      onClick={() => onRate(message, message.feedback === value ? 0 : value)}
      className={`rounded-sm px-1.5 py-0.5 text-sm transition-colors ${
        message.feedback === value ? "bg-rule-soft text-ink" : "text-muted hover:text-ink"
      }`}
    >
      {glyph}
    </button>
  );
  return (
    <div className="mt-2 flex items-center gap-1">
      {button(1, "Helpful", "👍")}
      {button(-1, "Not helpful", "👎")}
      {verifiable &&
        (message.verifiedSaved ? (
          <span className="ml-2 text-xs text-source">✓ Saved as the verified answer</span>
        ) : (
          <button
            type="button"
            onClick={() => onVerify(message)}
            title="Reuse this exact answer whenever someone asks this question"
            className="ml-2 rounded-sm px-1.5 py-0.5 text-xs text-muted hover:bg-source-soft hover:text-source"
          >
            ✓ Mark as verified
          </button>
        ))}
    </div>
  );
}

function Message({ message, onRate, onOpenSource, onVerify }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-lg rounded-br-sm bg-ink px-4 py-2.5 text-sm text-paper">
          {message.content}
        </p>
      </div>
    );
  }

  return (
    <div className="ruled-margin">
      <ResearchSteps steps={message.steps} live={message.streaming && !message.content} />
      {message.answer_kind === "verified" && (
        <p className="mb-2 inline-flex items-center gap-1.5 rounded-sm bg-source-soft px-2 py-0.5 text-xs font-medium text-source">
          <Icon.Check width={13} height={13} /> Verified answer
          {message.verified?.by && <span className="font-normal">· approved by {message.verified.by}</span>}
        </p>
      )}
      {message.answer_kind === "fallback" && (
        <p className="mb-2 inline-block rounded-sm bg-warn-soft px-2 py-0.5 text-xs text-warn">
          The AI model is unavailable right now — this is the closest matching passage, not a written answer.
        </p>
      )}
      <div className={`text-[15px] leading-relaxed ${message.quota ? "text-source" : "text-ink"}`}>
        <Answer content={message.content} />
        {message.streaming && <span className="stream-caret" />}
      </div>
      <Sources citations={message.citations} onOpen={(c) => onOpenSource?.(c, message)} />
      <Feedback message={message} onRate={onRate} onVerify={onVerify} />
    </div>
  );
}

function StarterCards({ suggestions, onPick }) {
  if (!suggestions.length) return null;
  return (
    <div className="mx-auto mt-6 grid max-w-3xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {suggestions.map((s) => (
        <button
          key={`${s.doc_id}-${s.question}`}
          type="button"
          onClick={() => onPick(s.question)}
          className="group rounded-lg border border-rule bg-surface p-4 text-left transition-colors hover:border-signal"
        >
          <span className="block text-sm text-ink group-hover:text-signal">{s.question}</span>
          <span className="mt-2 block truncate font-mono text-[11px] text-muted">{s.filename}</span>
        </button>
      ))}
    </div>
  );
}

export default function ChatPage() {
  const { token, user } = useAuth();
  const notify = useToast();
  const { conversationId, setConversationId, clearConversationId } = useConversationState();
  const [messages, setMessages] = useState([]);
  const [openSource, setOpenSource] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [slowRequest, setSlowRequest] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [deepResearch, setDeepResearch] = useState(false);
  // True while a question is in flight: the conversation loader must not
  // replace the optimistic messages with a half-saved server copy.
  const askingRef = useRef(false);
  const handledAskRef = useRef(null);
  const location = useLocation();
  const navigate = useNavigate();
  const slowRequestTimer = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    async function loadConversation() {
      try {
        const list = await api.listConversations(token);
        if (cancelled) return;
        setConversations(list);
        if (askingRef.current) return;

        if (!conversationId) {
          setMessages([]);
          return;
        }

        if (!list.some((conversation) => conversation.id === conversationId)) {
          clearConversationId();
          setMessages([]);
          return;
        }

        const detail = await api.getConversation(token, conversationId);
        if (cancelled) return;
        setMessages(
          detail.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            citations: m.citations || [],
            answer_kind: m.answer_kind,
            feedback: m.feedback,
            steps: m.research_steps || null,
          })),
        );
      } catch (err) {
        if (cancelled) return;
        if (err.status === 404) {
          clearConversationId();
        }
        setMessages([]);
      }
    }

    loadConversation();
    return () => {
      cancelled = true;
    };
  }, [token, conversationId, clearConversationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!token) return;
    api.getSuggestions(token).then(setSuggestions).catch(() => setSuggestions([]));
  }, [token]);

  // The server names a conversation after its first question; re-read the
  // list so the sidebar shows that title instead of "New conversation".
  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations(token));
    } catch {
      /* sidebar refresh is best-effort */
    }
  }, [token]);

  async function handleSubmit(e) {
    e.preventDefault();
    await ask(question);
  }

  /** `opts.fresh`: start a new conversation (questions sent from other pages). */
  async function ask(text, opts = {}) {
    const asked = (text || "").trim();
    if (!asked || busy || askingRef.current) return;
    askingRef.current = true;

    let activeConversationId = opts.fresh ? null : conversationId;
    if (!activeConversationId) {
      try {
        const created = await api.createConversation(token);
        activeConversationId = created.id;
        setConversationId(created.id);
      } catch (err) {
        console.error("createConversation failed:", err);
        notify(err.detail || "Couldn't start a new conversation. Please try again.");
        askingRef.current = false;
        setBusy(false);
        return;
      }
    }

    setQuestion("");
    setBusy(true);
    setSlowRequest(false);
    
    // Only if nothing at all has come back after 6 seconds is the server
    // probably asleep. Any step or text from the stream cancels the notice.
    slowRequestTimer.current = setTimeout(() => {
      setSlowRequest(true);
    }, 6000);
    const heardBack = () => {
      clearTimeout(slowRequestTimer.current);
      setSlowRequest(false);
    };

    setMessages((m) => [
      ...m,
      { role: "user", content: asked },
      { role: "assistant", content: "", citations: [], streaming: true },
    ]);

    const updateLast = (patch) =>
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = { ...next[next.length - 1], ...patch };
        return next;
      });

    let receivedAny = false;
    let receivedText = "";
    try {
      const steps = [];
      await api.askStream(token, asked, {
        conversationId: activeConversationId,
        mode: deepResearch ? "research" : "auto",
        onStep: (step) => {
          heardBack();
          receivedAny = true; // the server is running it: never retry (that would ask twice)
          steps.push(step);
          updateLast({ steps: [...steps] });
        },
        onToken: (chunk) => {
          heardBack();
          receivedAny = true;
          receivedText += chunk;
          updateLast({ content: receivedText });
        },
        onCitations: (citations) => updateLast({ citations }),
        onMeta: ({ id, answer_kind, verified }) => updateLast({ id, answer_kind, verified }),
      });
      updateLast({ streaming: false });
    } catch (err) {
      if (err?.status === 429) {
        const detail = err.detail || "Citebase is busy right now. Please try again in a moment.";
        updateLast({ content: detail, streaming: false, quota: true });
        notify(detail, "info");
        return;
      }

      // If the server already started answering, it has counted the question
      // and saved it; asking again via /ask would charge and store it twice.
      if (receivedAny || err?.status) {
        updateLast({
          content: receivedAny
            ? `${receivedText}\n\n_The connection dropped before the answer finished. Ask again to get the rest._`
            : `That question couldn't be answered just now (HTTP ${err.status}${err.detail ? `: ${err.detail}` : ""}).`,
          streaming: false,
        });
        notify(err?.detail || "The answer was interrupted.");
        return;
      }

      // The stream never reached the server (network error): safe to retry once.
      try {
        const res = await api.ask(token, asked, activeConversationId, deepResearch ? "research" : "auto");
        updateLast({
          content: res.answer,
          citations: res.citations,
          id: res.message_id,
          answer_kind: res.answer_kind,
          verified: res.verified,
          steps: res.research_steps || null,
          streaming: false,
        });
      } catch (fallbackErr) {
        if (fallbackErr?.status === 429) {
          const detail = fallbackErr.detail || "Citebase is busy right now. Please try again in a moment.";
          updateLast({ content: detail, streaming: false, quota: true });
          notify(detail, "info");
          return;
        }
        const status = fallbackErr?.status ?? err?.status ?? "unknown";
        const detail = fallbackErr?.detail ?? err?.detail ?? fallbackErr?.message ?? err?.message ?? "The server did not provide more detail.";
        updateLast({
          content: `That question couldn't be answered just now (HTTP ${status}${detail ? `: ${detail}` : ""}).`,
          streaming: false,
        });
        notify(detail);
      }
    } finally {
      askingRef.current = false;
      refreshConversations();
      if (slowRequestTimer.current) {
        clearTimeout(slowRequestTimer.current);
        slowRequestTimer.current = null;
      }
      setSlowRequest(false);
      setBusy(false);
    }
  }

  const canVerify = hasRole(user, "ADMIN");
  async function verify(message) {
    try {
      await api.verifyAnswer(token, message.id);
      setMessages((all) => all.map((m) => (m.id === message.id ? { ...m, verifiedSaved: true } : m)));
      notify("Saved. Anyone who asks this question now gets this answer, marked as verified.", "info");
    } catch (err) {
      notify(err.detail || "Couldn't save the verified answer.");
    }
  }

  async function rate(message, value) {
    setMessages((all) => all.map((m) => (m.id === message.id ? { ...m, feedback: value || null } : m)));
    try {
      await api.rateAnswer(token, message.id, value);
    } catch (err) {
      notify(err.detail || "Couldn't save your feedback.");
    }
  }

  // Quick ask (from any page) arrives as router state: ask it once, then clear
  // the state so a refresh doesn't ask again.
  const pendingAsk = location.state?.ask;
  useEffect(() => {
    if (!pendingAsk || !token || handledAskRef.current === location.key) return;
    handledAskRef.current = location.key; // React may run effects twice; ask once
    navigate(location.pathname, { replace: true, state: null });
    clearConversationId();
    setMessages([]);
    ask(pendingAsk, { fresh: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingAsk, token]);

  // "New question" in the sidebar: start from a clean slate.
  const freshRequest = location.state?.fresh;
  useEffect(() => {
    if (!freshRequest) return;
    navigate(location.pathname, { replace: true, state: null });
    if (askingRef.current) return;
    clearConversationId();
    setMessages([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [freshRequest]);

  async function startNewConversation() {
    if (busy) return; // switching mid-answer would lose the answer being written
    try {
      const created = await api.createConversation(token);
      setConversationId(created.id);
      setMessages([]);
    } catch (err) {
      console.error("startNewConversation error:", err);
      notify(err.detail || err.message || "Unable to start a new conversation.");
    }
  }

  async function selectConversation(id) {
    if (busy || id === conversationId) return;
    setConversationId(id);
    setMessages([]);
  }

  async function deleteConversation(id) {
    if (!window.confirm("Delete this conversation?")) return;
    try {
      await api.deleteConversation(token, id);
      const next = conversations.filter((conversation) => conversation.id !== id);
      setConversations(next);
      if (conversationId === id) {
        const fallback = next[0]?.id ?? null;
        setConversationId(fallback);
        setMessages([]);
      }
    } catch (err) {
      console.error("deleteConversation error:", err);
      notify(err.detail || err.message || "Unable to delete this conversation.");
    }
  }

  return (
    <>
      <main className="mx-auto flex h-[calc(100dvh-3.5rem)] min-h-0 max-w-6xl flex-1 flex-col px-4 py-4 sm:px-5 lg:h-dvh lg:flex-row lg:gap-6 lg:py-5">
      <aside className="mb-3 max-h-36 w-full shrink-0 overflow-y-auto rounded-lg border border-rule bg-surface/80 p-3 lg:mb-0 lg:max-h-none lg:w-72">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">Conversations</h2>
          <Button variant="secondary" size="sm" onClick={startNewConversation} disabled={busy}>
            New
          </Button>
        </div>
        <div className="space-y-2">
          {conversations.map((conversation) => (
            <div
              key={conversation.id}
              className={`rounded-md border p-2 text-sm ${conversation.id === conversationId ? "border-signal bg-rule-soft" : "border-rule bg-paper"}`}
            >
              <button
                className="flex w-full items-start justify-between gap-2 text-left disabled:cursor-wait"
                disabled={busy}
                onClick={() => selectConversation(conversation.id)}
              >
                <span className="line-clamp-2 flex-1 text-ink">{conversation.title || "New conversation"}</span>
                <span className="text-[11px] text-muted">{new Date(conversation.updated_at).toLocaleDateString()}</span>
              </button>
              <button className="mt-2 text-xs text-danger" onClick={() => deleteConversation(conversation.id)}>
                Delete
              </button>
            </div>
          ))}
        </div>
      </aside>

      <section className="flex min-h-0 flex-1 flex-col">
        <div className="flex-1 space-y-6 overflow-y-auto py-2">
          {messages.length === 0 ? (
            <div>
              <EmptyState title="Ask about your documents">
                {suggestions.length
                  ? "Start with one of these, or type your own. Every answer names the file it came from."
                  : "Try “What is the notice period?” or “Summarise the travel policy.” Every answer names the file it came from."}
              </EmptyState>
              <StarterCards suggestions={suggestions} onPick={ask} />
            </div>
          ) : (
            messages.map((m, i) => (
              <Message
                key={m.id || i}
                message={m}
                onRate={rate}
                onVerify={canVerify ? verify : undefined}
                onOpenSource={(c, msg) => {
                  const idx = messages.indexOf(msg);
                  const asked = [...messages.slice(0, idx)].reverse().find((x) => x.role === "user");
                  setOpenSource({ citation: c, question: asked?.content || "" });
                }}
              />
            ))
          )}
          {slowRequest && busy && (
            <div className="flex items-center gap-2 px-4 py-3 text-sm text-muted">
              <span className="animate-spin">⏳</span>
              <span>Still waiting for the server. After a quiet spell it can take up to a minute to wake up.</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={handleSubmit} className="border-t border-rule bg-paper py-4">
          <div className="flex items-end gap-2">
            <textarea
              rows={1}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) handleSubmit(e);
              }}
              aria-label="Your question"
              placeholder="Ask a question…"
              className="max-h-40 flex-1 resize-none rounded-md border border-rule bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-muted focus:border-signal focus:outline-none"
            />
            <Button type="submit" disabled={busy || !question.trim()}>
              {busy ? "Thinking…" : "Ask"}
            </Button>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <p className="font-mono text-[11px] text-muted">Enter to send · Shift+Enter for a new line</p>
            <label
              className="flex cursor-pointer items-center gap-2 text-xs text-ink-soft"
              title="Plans several searches across your documents before answering. Slower, better for comparisons and 'do these conflict?' questions."
            >
              <input
                type="checkbox"
                checked={deepResearch}
                onChange={(e) => setDeepResearch(e.target.checked)}
                className="accent-[var(--color-signal)]"
              />
              Deep research
            </label>
          </div>
        </form>
      </section>
    </main>
      {openSource && (
        <PassagePanel
          citation={openSource.citation}
          question={openSource.question}
          onClose={() => setOpenSource(null)}
        />
      )}
    </>
  );
}
