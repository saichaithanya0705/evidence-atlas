export const API_BASE_URL = (import.meta.env.VITE_API_URL || "/api").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

function csrfToken() {
  return document.cookie.split("; ").find((part) => part.startsWith("evidence_csrf="))?.split("=").slice(1).join("=") || "";
}

async function request(path, options = {}) {
  let response;
  try {
    const method = options.method || "GET";
    response = await fetch(API_BASE_URL + path, {
      ...options,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(method !== "GET" && path !== "/auth/login" ? { "X-CSRF-Token": csrfToken() } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    throw new ApiError("The research service could not be reached. Please try again shortly.", 0, error);
  }
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login" && path !== "/auth/me") {
      window.dispatchEvent(new Event("evidence-session-expired"));
    }
    const detail = typeof payload === "object" && payload ? payload.detail || payload.message : payload;
    throw new ApiError(typeof detail === "string" && detail.trim() ? detail : `Request failed (${response.status}).`, response.status, payload);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new ApiError("The research service returned an unexpected response.", response.status, payload);
  }
  return payload;
}

export const getHealth = () => request("/health");
export const getSession = () => request("/auth/me");
export const login = (username, password) => request("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
export const logout = () => request("/auth/logout", { method: "POST" });
export const changePassword = (current_password, new_password) => request("/auth/password", { method: "POST", body: JSON.stringify({ current_password, new_password }) });
export const getPaper = (pmid) => request("/paper/" + encodeURIComponent(pmid));

export const createConversation = () => request("/conversations", { method: "POST", body: JSON.stringify({}) });
export const listConversations = ({ limit = 50, offset = 0 } = {}) => request("/conversations?" + new URLSearchParams({ limit, offset }));
export const getConversation = (conversationId, { limit = 100, offset = 0 } = {}) => request("/conversations/" + encodeURIComponent(conversationId) + "?" + new URLSearchParams({ limit, offset }));
export const submitConversationTurn = (conversationId, payload) => request("/conversations/" + encodeURIComponent(conversationId) + "/turns", { method: "POST", body: JSON.stringify(payload) });

export function runResearch({ query, yearMin, yearMax, studyTypes, maxLoops }, isAdmin = false) {
  const body = { query };
  if (isAdmin) {
    if (yearMin) body.year_min = Number(yearMin);
    if (yearMax) body.year_max = Number(yearMax);
    if (studyTypes?.length) body.study_types = studyTypes;
    if (maxLoops) body.max_loops = maxLoops;
  }
  return request("/research", { method: "POST", body: JSON.stringify(body) });
}

export const listAudits = (params = {}) => request("/admin/audits?" + new URLSearchParams(params));
export const getAudit = (id) => request("/admin/audits/" + encodeURIComponent(id));
export const getObservability = (days = 30) => request("/admin/observability?days=" + days);
export const getEvaluations = () => request("/admin/evaluations");
export const getEvaluation = (runId) => request("/admin/evaluations/" + encodeURIComponent(runId));
export const listAccounts = (params = {}) => request("/admin/accounts?" + new URLSearchParams(params));
export const createAccount = (payload) => request("/admin/accounts", { method: "POST", body: JSON.stringify(payload) });
export const updateAccount = (id, payload) => request("/admin/accounts/" + encodeURIComponent(id), { method: "PATCH", body: JSON.stringify(payload) });
