// HTTP client for the SafariAI API. Reads fail soft (a fallback value), asks throw so the UI can say so.

const JSON_HEADERS = { "Content-Type": "application/json" };

async function getJson(path, fallback) {
  try {
    const response = await fetch(path);
    if (!response.ok) return fallback;
    return await response.json();
  } catch {
    return fallback;
  }
}

export const fetchParks = () => getJson("/v1/parks", []);
export const fetchStatus = () => getJson("/v1/status", null);
export const fetchDocuments = () => getJson("/v1/documents", []);

export async function ask(body, signal) {
  const response = await fetch("/v1/ask", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw new Error(`ask failed (${response.status})`);
  return response.json();
}

function parseEvent(raw) {
  let event = "message";
  const data = [];
  for (const line of raw.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

/**
 * Ask over Server-Sent Events. Falls back to the JSON endpoint when streaming
 * is unavailable or breaks before any text arrived.
 */
export async function askStream(body, { signal, onStatus, onDelta, onReset } = {}) {
  let response;
  try {
    response = await fetch("/v1/ask/stream", {
      method: "POST",
      headers: { ...JSON_HEADERS, Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    return ask(body, signal);
  }
  if (!response.ok || !response.body) return ask(body, signal);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let receivedText = false;
  let final = null;

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const parsed = parseEvent(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (!parsed) continue;
        const { event, data } = parsed;
        if (event === "status") onStatus?.(data.label || "");
        else if (event === "delta") {
          receivedText = true;
          onDelta?.(data.text || "");
        } else if (event === "reset") {
          // The agent stopped drafting to look something up; the text so far is discarded.
          receivedText = false;
          onReset?.();
        } else if (event === "final") final = data;
        else if (event === "error") throw new Error(data.message || "The desk could not answer.");
      }
    }
  } catch (error) {
    if (error.name === "AbortError" || receivedText) throw error;
    return ask(body, signal);
  }
  if (final) return final;
  if (receivedText) throw new Error("The answer was cut off.");
  return ask(body, signal);
}

export async function sendFeedback(payload) {
  try {
    await fetch("/v1/feedback", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(payload) });
    return true;
  } catch {
    return false;
  }
}

export async function downloadBriefing(payload) {
  const response = await fetch("/v1/briefing?download=true", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`briefing failed (${response.status})`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "safari-briefing.pdf";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function adminHeaders(token) {
  return token ? { "X-Admin-Token": token } : {};
}

export async function runHarvest(token) {
  const response = await fetch("/v1/admin/harvest", { method: "POST", headers: adminHeaders(token) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `harvest failed (${response.status})`);
  return payload;
}

export async function uploadDocument(token, file, metadata) {
  const form = new FormData();
  form.append("file", file);
  form.append("metadata", JSON.stringify(metadata));
  const response = await fetch("/v1/documents", { method: "POST", headers: adminHeaders(token), body: form });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `upload failed (${response.status})`);
  return payload;
}
