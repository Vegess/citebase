const BASE = import.meta.env.VITE_API_URL || "";
// Session endpoints go through the site's own origin (Vercel rewrites /api/*
// to the API), so the httpOnly session cookie is first-party.
const SESSION_BASE = import.meta.env.VITE_SESSION_BASE ?? "/api";

/* Access tokens last 30 minutes. When one is rejected, AuthContext swaps in a
   fresh one from the session cookie and the request is retried once. */
let tokenRefresher = null;
export function setTokenRefresher(fn) {
  tokenRefresher = fn;
}

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

async function request(path, opts = {}) {
  try {
    return await rawRequest(path, opts);
  } catch (err) {
    if (err.status === 401 && opts.token && !opts.retried && tokenRefresher) {
      const fresh = await tokenRefresher();
      if (fresh) return rawRequest(path, { ...opts, token: fresh, retried: true });
    }
    throw err;
  }
}

async function rawRequest(path, { token, method = "GET", body, form, signal } = {}) {
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

export const getProviders = () => request("/auth/providers");

/** Full-page navigation target that starts Google/GitHub sign-in. */
export const oauthStartUrl = (provider) => `${BASE}/auth/oauth/${provider}/start`;

export const deleteWorkspace = (token, confirmName) =>
  request("/org", { token, method: "DELETE", body: { confirm_name: confirmName } });

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

export function uploadDocument(token, file, collectionId = null) {
  const fd = new FormData();
  fd.append("file", file);
  if (collectionId) fd.append("collection_id", collectionId);
  return request("/documents", { token, method: "POST", body: fd });
}

export function uploadVersion(token, docId, file) {
  const fd = new FormData();
  fd.append("file", file);
  return request(`/documents/${docId}/versions`, { token, method: "POST", body: fd });
}

export const getDocumentDetail = (token, id) => request(`/documents/${id}/detail`, { token });
export const moveDocument = (token, id, collectionId) =>
  request(`/documents/${id}`, { token, method: "PATCH", body: { collection_id: collectionId || null } });
export const reviewConflicts = (token, id, state) =>
  request(`/documents/${id}/conflicts`, { token, method: "POST", body: { state } });

export const listCollections = (token) => request("/collections", { token });
export const createCollection = (token, body) => request("/collections", { token, method: "POST", body });
export const updateCollection = (token, id, body) => request(`/collections/${id}`, { token, method: "PATCH", body });
export const deleteCollection = (token, id) => request(`/collections/${id}`, { token, method: "DELETE" });

export const verifyAnswer = (token, messageId) =>
  request(`/chat/messages/${messageId}/verify`, { token, method: "POST" });
export const removeVerified = (token, id) => request(`/verified/${id}`, { token, method: "DELETE" });

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
  const open = (bearer) =>
    fetch(`${BASE}/chat/ask/stream`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${bearer}`,
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ question, conversation_id: conversationId, mode }),
      signal,
    });
  let res = await open(token);
  if (res.status === 401 && tokenRefresher) {
    const fresh = await tokenRefresher();
    if (fresh) res = await open(fresh);
  }

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
    if (parsed.message_id) onMeta?.({ id: parsed.message_id, answer_kind: parsed.answer_kind, verified: parsed.verified });
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

/* ---------------- sessions (cookie, same origin) ---------------- */

async function sessionCall(path, { token, method = "POST", body } = {}) {
  const headers = { "X-Requested-With": "citebase" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${SESSION_BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await parseError(res, path);
  return res.status === 204 ? null : res.json();
}

export const startSession = (token) => sessionCall("/auth/session", { token });
export const refreshSession = () => sessionCall("/auth/refresh");
export const endSession = () => sessionCall("/auth/logout");

/* ---------------- account & password ---------------- */

export const getAccount = (token) => request("/account", { token });
export const changePassword = (token, currentPassword, newPassword) =>
  request("/account/password", {
    token,
    method: "POST",
    body: { current_password: currentPassword || null, new_password: newPassword },
  });
export const signOutEverywhere = (token) => request("/account/sign-out-everywhere", { token, method: "POST" });
export const linkProvider = (token, provider) => request(`/account/link/${provider}`, { token, method: "POST" });
export const unlinkProvider = (token, provider) =>
  request(`/account/identities/${provider}`, { token, method: "DELETE" });
export const requestVerification = (token) => request("/account/verify-email", { token, method: "POST" });
export const confirmEmail = (verifyToken) => request("/auth/verify-email", { method: "POST", body: { token: verifyToken } });
export const forgotPassword = (email) => request("/auth/forgot-password", { method: "POST", body: { email } });
export const previewReset = (resetToken) => request(`/auth/password-reset/${encodeURIComponent(resetToken)}`);
export const resetPassword = (resetToken, password) =>
  request("/auth/password-reset", { method: "POST", body: { token: resetToken, password } });
export const createResetLink = (token, userId) =>
  request(`/org/members/${userId}/reset-link`, { token, method: "POST" });
export const renameWorkspace = (token, name) => request("/org", { token, method: "PATCH", body: { name } });

/* ---------------- home, samples, passages ---------------- */

export const getHome = (token) => request("/home", { token });
export const loadSamples = (token) => request("/documents/samples", { token, method: "POST" });
export const getPassage = (token, { docId, filename, chunkIndex }) => {
  const q = new URLSearchParams({ chunk_index: String(chunkIndex) });
  if (docId) q.set("doc_id", docId);
  else q.set("filename", filename);
  return request(`/documents/passage?${q}`, { token });
};
