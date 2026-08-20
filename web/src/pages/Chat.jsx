import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import { Button, EmptyState, useToast } from "../components/ui";
import { useConversationState } from "../hooks/useConversationState";

/**
 * Sources are the point of the product: an answer you cannot trace is an
 * answer you cannot use. They get their own colour and the document's own
 * vocabulary — filename, chunk index — rather than being tucked away.
 */
function Sources({ citations }) {
  if (!citations?.length) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {citations.map((c, i) => (
        <span
          key={`${c.filename}-${c.chunk_index}-${i}`}
          className="inline-flex items-center gap-1.5 rounded-sm border border-source/20 bg-source-soft px-2 py-1 font-mono text-[11px] text-source"
        >
          <span className="opacity-60">{i + 1}</span>
          <span className="max-w-[220px] truncate">{c.filename}</span>
          <span className="opacity-60">#{c.chunk_index}</span>
        </span>
      ))}
    </div>
  );
}

function Message({ message }) {
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
      <p className={`whitespace-pre-wrap text-[15px] leading-relaxed ${message.quota ? "text-source" : "text-ink"}`}>
        {message.content}
        {message.streaming && <span className="stream-caret" />}
      </p>
      <Sources citations={message.citations} />
    </div>
  );
}

export default function ChatPage() {
  const { token } = useAuth();
  const notify = useToast();
  const { conversationId, setConversationId, clearConversationId } = useConversationState();
  const [messages, setMessages] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    async function loadConversation() {
      try {
        const list = await api.listConversations(token);
        if (cancelled) return;
        setConversations(list);

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

  async function handleSubmit(e) {
    e.preventDefault();
    const asked = question.trim();
    if (!asked || busy) return;

    let activeConversationId = conversationId;
    if (!activeConversationId) {
      try {
        const created = await api.createConversation(token);
        activeConversationId = created.id;
        setConversationId(created.id);
      } catch (err) {
        console.error("createConversation failed:", err);
        const message = err.detail || err.message || "Unable to start a new conversation.";
        const url = err.url ? ` URL=${err.url}` : "";
        notify(`${message}${url}`);
        setBusy(false);
        return;
      }
    }

    setQuestion("");
    setBusy(true);
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

    try {
      let text = "";
      await api.askStream(token, asked, {
        conversationId: activeConversationId,
        onToken: (chunk) => {
          text += chunk;
          updateLast({ content: text });
        },
        onCitations: (citations) => updateLast({ citations }),
      });
      updateLast({ streaming: false });
    } catch (err) {
      if (err?.status === 429) {
        const detail = err.detail || "The demo is busy right now. Please try again in a moment.";
        updateLast({ content: detail, streaming: false, quota: true });
        notify(detail, "info");
        return;
      }

      // Fall back to the non-streaming endpoint before giving up on the answer.
      try {
        const res = await api.ask(token, asked, activeConversationId);
        updateLast({ content: res.answer, citations: res.citations, streaming: false });
      } catch (fallbackErr) {
        if (fallbackErr?.status === 429) {
          const detail = fallbackErr.detail || "The demo is busy right now. Please try again in a moment.";
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
      setBusy(false);
    }
  }

  async function startNewConversation() {
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
    <main className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-6xl flex-col px-5 py-5 lg:flex-row lg:gap-6">
      <aside className="mb-4 w-full shrink-0 rounded-lg border border-rule bg-surface/80 p-3 lg:mb-0 lg:w-72">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">Conversations</h2>
          <Button variant="secondary" size="sm" onClick={startNewConversation}>
            New
          </Button>
        </div>
        <div className="space-y-2">
          {conversations.map((conversation) => (
            <div
              key={conversation.id}
              className={`rounded-md border p-2 text-sm ${conversation.id === conversationId ? "border-signal bg-rule-soft" : "border-rule bg-paper"}`}
            >
              <button className="flex w-full items-start justify-between gap-2 text-left" onClick={() => selectConversation(conversation.id)}>
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
            <EmptyState title="Ask about your documents">
              Try “What is the notice period?” or “Summarise the renewal terms.” Every
              answer names the file it came from.
            </EmptyState>
          ) : (
            messages.map((m, i) => <Message key={m.id || i} message={m} />)
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
                if (e.key === "Enter" && !e.shiftKey) handleSubmit(e);
              }}
              placeholder="Ask a question…"
              className="max-h-40 flex-1 resize-none rounded-md border border-rule bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-muted focus:border-signal focus:outline-none"
            />
            <Button type="submit" disabled={busy || !question.trim()}>
              {busy ? "Thinking…" : "Ask"}
            </Button>
          </div>
          <p className="mt-2 font-mono text-[11px] text-muted">
            Enter to send · Shift+Enter for a new line
          </p>
        </form>
      </section>
    </main>
  );
}
