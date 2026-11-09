// Admin API client. Every call sends the admin session token when there is one; a 401 surfaces as AuthError.

import { readAdminToken, saveAdminToken } from "../storage";
import { justRefreshed } from "./data";

export class AuthError extends Error {}

let authHandler = () => {};

/** The dashboard registers one handler that shows the sign-in screen on any 401. */
export function onAuthError(handler) {
  authHandler = handler;
}

export const readToken = readAdminToken;
export const saveToken = saveAdminToken;

/** Exchanges the admin username and password for a session token and stores it. */
export async function login(username, password) {
  const response = await fetch("/v1/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Sign-in failed (${response.status})`);
  saveAdminToken(payload.token);
  return payload;
}

function headers(extra = {}) {
  const token = readToken();
  return token ? { ...extra, "X-Admin-Token": token } : extra;
}

function query(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== "" && value !== null && value !== undefined) search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: headers(options.headers) });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401) {
    authHandler(payload.detail);
    throw new AuthError(payload.detail || "Sign in to continue");
  }
  if (!response.ok) throw new Error(payload.detail || `${path} failed (${response.status})`);
  return payload;
}

export const checkSession = () => request("/v1/admin/session");
export const fetchOverview = (days, fresh = false) => request(`/v1/admin/overview${query({ days, fresh: fresh ? "true" : "" })}`);
export const fetchQuestions = (params) => request(`/v1/admin/questions${query(params)}`);
export const fetchFeedback = (params) => request(`/v1/admin/feedback${query(params)}`);
export const reviewFeedback = (id, status, note = "") =>
  request(`/v1/admin/feedback/${encodeURIComponent(id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, note }),
  });
export const fetchInventory = () => request("/v1/admin/inventory");
export const fetchFees = (params) => request(`/v1/admin/fees${query(params)}`);
export const fetchDocuments = () => request("/v1/admin/documents");
export const deleteDocument = (id) => request(`/v1/admin/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
export const fetchStatus = () => request("/v1/status");
export const runHarvest = (full = false) => request(`/v1/admin/harvest${query({ full: full ? "true" : "" })}`, { method: "POST" });
export const fetchHarvests = () => request("/v1/admin/harvests");
export const fetchSystem = () => request("/v1/admin/system");
export const fetchEvaluation = () => request("/v1/admin/evaluation");
export const runEvaluation = () => request("/v1/evaluate", { method: "POST" });

export function uploadDocument(file, metadata) {
  const form = new FormData();
  form.append("file", file);
  form.append("metadata", JSON.stringify(metadata));
  return request("/v1/documents", { method: "POST", body: form });
}

// Queries for the shared cache (see data.js): [key, load]. Keys encode every parameter.
const keyed = (name, params = {}) => `${name}${query(params)}`;
export const queries = {
  // After Refresh the server recomputes instead of answering from its cache.
  overview: (days) => [keyed("overview", { days }), () => fetchOverview(days, justRefreshed())],
  questions: (params) => [keyed("questions", params), () => fetchQuestions(params)],
  feedback: (params) => [keyed("feedback", params), () => fetchFeedback(params)],
  inventory: () => ["inventory", fetchInventory],
  fees: (params) => [keyed("fees", params), () => fetchFees(params)],
  documents: () => ["documents", fetchDocuments],
  status: () => ["status", fetchStatus],
  harvests: () => ["harvests", fetchHarvests],
  system: () => ["system", fetchSystem],
  evaluation: () => ["evaluation", fetchEvaluation],
  parks: () => ["parks", () => request("/v1/parks")],
};

export async function downloadQuestionsCsv(days) {
  const response = await fetch(`/v1/admin/questions.csv${query({ days })}`, { headers: headers() });
  if (response.status === 401) throw new AuthError("Sign in to continue");
  if (!response.ok) throw new Error(`export failed (${response.status})`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `safari-questions-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
