const configuredBaseUrl = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
export const API_BASE_URL = configuredBaseUrl.replace(/\/+$/, "");
const ADMIN_KEY_STORAGE = "evidence-atlas-admin-key";

export function getAdminKey() {
  try { return sessionStorage.getItem(ADMIN_KEY_STORAGE) || ""; } catch { return ""; }
}

export function setAdminKey(value) {
  try { sessionStorage.setItem(ADMIN_KEY_STORAGE, value); } catch { /* private mode */ }
}

export function clearAdminKey() {
  try { sessionStorage.removeItem(ADMIN_KEY_STORAGE); } catch { /* private mode */ }
}

export class ApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(API_BASE_URL + path, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(getAdminKey() ? { "X-Admin-Key": getAdminKey() } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    throw new ApiError(
      "The research API could not be reached. Check that the backend is running and VITE_API_URL is correct.",
      0,
      error,
    );
  }

  const contentType = response.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json")) {
    payload = await response.json().catch(() => null);
  } else {
    payload = await response.text().catch(() => "");
  }

  if (!response.ok) {
    const detail = payload && typeof payload === "object"
      ? payload.detail || payload.message
      : payload;
    throw new ApiError(
      typeof detail === "string" && detail.trim()
        ? detail
        : "The research API returned an error (" + response.status + ").",
      response.status,
      payload,
    );
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new ApiError("The research API returned an unexpected response format.", response.status, payload);
  }
  return payload;
}

export function verifyAdmin() {
  return request("/admin/verify", { method: "POST" });
}

export function getHealth() {
  return request("/health");
}

export function analyzeQuery(query) {
  return request("/analyze-query", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

export function runResearch({ query, yearMin, yearMax, studyTypes, maxLoops = 2 }) {
  const body = {
    query,
    max_loops: maxLoops,
  };
  if (yearMin) body.year_min = Number(yearMin);
  if (yearMax) body.year_max = Number(yearMax);
  if (studyTypes.length) body.study_types = studyTypes;
  return request("/research", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getPaper(pmid) {
  return request("/paper/" + encodeURIComponent(pmid));
}

export function getTraceUrl(auditTraceUrl, requestId) {
  const fallback = "/trace/" + encodeURIComponent(requestId);
  if (!auditTraceUrl) return fallback;

  try {
    const url = new URL(auditTraceUrl, API_BASE_URL + "/");
    const base = new URL(API_BASE_URL + "/");
    if (url.origin !== base.origin) {
      throw new ApiError("The API returned a trace URL outside the configured research service.", 0);
    }
    return url.pathname + url.search;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("The API returned an invalid audit-trace URL.", 0, error);
  }
}

export function getTrace(auditTraceUrl, requestId) {
  if (!requestId && !auditTraceUrl) {
    throw new ApiError("No request identifier or trace URL was returned for this research run.", 0);
  }
  return request(getTraceUrl(auditTraceUrl, requestId));
}
