const BASE = import.meta.env.VITE_API_URL || "";

export class ApiError extends Error {
  constructor(status, detail, url) {
    super(detail || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
    this.url = url;
  }
}

async function parseError(res, url) {
  let detail = null;
  try {
    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail[0]?.msg ?? null;
      else if (typeof body === "string") detail = body;
    } else {
      detail = await res.text();
    }
  } catch {
    /* response had no readable body */
  }
  return new ApiError(res.status, detail, url);
}

async function request(path, { token, method = "GET", body, form, signal } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  let payload;
  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form).toString();
  } else if (body instanceof FormData) {
    payload = body; // browser sets the multipart boundary
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const url = `${BASE}${path}`;
  const fetchOpts = { method, headers };
  if (signal) fetchOpts.signal = signal;
  if (payload !== undefined) fetchOpts.body = payload;

  let res;
  try {
    res = await fetch(url, fetchOpts);
  } catch (err) {
    // Never log headers or bodies: they carry the bearer token and passwords.
    console.error("api.request fetch failed", { url, method, error: err?.message });
    const error = new ApiError(null, `Network request failed: ${err.message}`, url);
    error.status = null;
    throw error;
  }

  if (!res.ok) throw await parseError(res, url);
  if (res.status === 204) return null;
  return res.json();
}

/* ---------------- server wake-up ---------------- */

/**
 * Free hosting puts the API to sleep when idle. Ping it as soon as the site
 * opens so it is awake by the time someone signs in or asks. Resolves when
 * the server answers; retries for up to ~3 minutes.
 */
export async function wakeServer({ attempts = 18, delayMs = 10_000 } = {}) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const res = await fetch(`${BASE}/ping`, { cache: "no-store" });
      if (res.ok) return true;
    } catch {
      /* still asleep or starting */
    }
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  return false;
}

/* ---------------- auth ---------------- */

export const signup = (email, password, orgName) =>
  request("/auth/signup", {
    method: "POST",
    body: { email, password, org_name: orgName },
  });

export const login = (email, password) =>
  request("/auth/login", {
    method: "POST",
    form: { username: email, password },
  });

export const getMe = (token) => request("/me", { token });

/* ---------------- documents ---------------- */

export const listDocuments = (token) => request("/documents", { token });

export const getDocument = (token, id) => request(`/documents/${id}`, { token });

export const deleteDocument = (token, id) =>
  request(`/documents/${id}`, { token, method: "DELETE" });

export function uploadDocument(token, file) {
  const fd = new FormData();
  fd.append("file", file);
  return request("/documents", { token, method: "POST", body: fd });
}

/* ---------------- org: members, invites, audit ---------------- */

export const listMembers = (token) => request("/org/members", { token });

export const changeMemberRole = (token, userId, role) =>
  request(`/org/members/${userId}`, { token, method: "PATCH", body: { role } });

export const removeMember = (token, userId) =>
  request(`/org/members/${userId}`, { token, method: "DELETE" });

export const listInvites = (token) => request("/org/invites", { token });

export const createInvite = (token, email, role) =>
  request("/org/invites", { token, method: "POST", body: { email, role } });

export const revokeInvite = (token, inviteId) =>
  request(`/org/invites/${inviteId}`, { token, method: "DELETE" });

export const listAudit = (token, limit = 30) => request(`/org/audit?limit=${limit}`, { token });

export const previewInvite = (inviteToken) =>
  request(`/auth/invites/${encodeURIComponent(inviteToken)}`);

export const acceptInvite = (inviteToken, password) =>
  request("/auth/accept-invite", { method: "POST", body: { token: inviteToken, password } });

/* ---------------- suggestions, feedback, insights ---------------- */

export const getSuggestions = (token) => request("/documents/suggestions", { token });

export const rateAnswer = (token, messageId, value) =>
  request(`/chat/messages/${messageId}/feedback`, { token, method: "POST", body: { value } });

export const getInsights = (token, days = 30) => request(`/insights?days=${days}`, { token });

/* ---------------- chat ---------------- */

export const ask = (token, question, conversationId, mode = "auto") =>
  request("/chat/ask", { token, method: "POST", body: { question, conversation_id: conversationId, mode } });

export const createConversation = (token) => request("/chat/conversations", { token, method: "POST" });

export const listConversations = (token) => request("/chat/conversations", { token });

export const getConversation = (token, conversationId) =>
  conversationId ? request(`/chat/conversations/${conversationId}`, { token }) : Promise.resolve(null);

export const deleteConversation = (token, conversationId) =>
  request(`/chat/conversations/${conversationId}`, { token, method: "DELETE" });

/**
 * Streams an answer from POST /chat/ask/stream.
 *
 * The backend emits Server-Sent Events. Each `data:` line is either JSON
 * or a bare token; both are handled. Recognised JSON shapes:
 *   { "text": "..."} | { "delta": "..." } | { "content": "..." }  -> appended
 *   { "citations": [...] }                                        -> final sources
 *   { "error": "..." }                                            -> surfaced
 * A `data: [DONE]` sentinel ends the stream.
 *
 * onToken(textChunk)  — called as text arrives
 * onCitations(list)   — called once sources are known
 */
export async function askStream(
  token,
  question,
  { conversationId, mode = "auto", onToken, onCitations, onMeta, onStep, signal } = {},
) {
  const res = await fetch(`${BASE}/chat/ask/stream`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ question, conversation_id: conversationId, mode }),
    signal,
  });

  if (!res.ok) throw await parseError(res);
  if (!res.body) throw new ApiError(500, "This browser cannot read streamed responses");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleLine = (line) => {
    if (!line.startsWith("data:")) return;
    const raw = line.slice(5).trim();
    if (!raw || raw === "[DONE]") return;

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      onToken?.(raw); // plain-text token stream
      return;
    }

    if (parsed.error) throw new ApiError(500, parsed.error);
    if (parsed.citations) onCitations?.(parsed.citations);
    if (parsed.message_id) onMeta?.({ id: parsed.message_id, answer_kind: parsed.answer_kind });
    if (parsed.step) onStep?.(parsed.step);

    const text = parsed.text ?? parsed.delta ?? parsed.content;
    if (typeof text === "string" && text) onToken?.(text);
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? ""; // keep the trailing partial line
    for (const line of lines) handleLine(line.trim());
  }

  if (buffer.trim()) handleLine(buffer.trim());
}
