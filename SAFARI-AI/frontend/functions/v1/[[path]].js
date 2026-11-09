// Cloudflare Pages Function: forwards /v1/* to the SafariAI API on Render, so the browser stays
// on one origin (the same job nginx.conf does in Docker). Streaming answers pass straight through.
//
// Pages environment variables:
//   API_ORIGIN    https://<service>.onrender.com
//   PROXY_SECRET  same value as SAFARI_PROXY_SECRET on the API (optional, recommended)

const HOP_HEADERS = ["host", "connection", "keep-alive", "transfer-encoding", "upgrade", "x-proxy-secret"];

export async function onRequest({ request, env }) {
  if (!env.API_ORIGIN) {
    return Response.json({ detail: "API_ORIGIN is not configured" }, { status: 500 });
  }
  const url = new URL(request.url);
  const target = new URL(url.pathname + url.search, env.API_ORIGIN);

  const headers = new Headers(request.headers);
  for (const name of HOP_HEADERS) headers.delete(name);
  // The API rate-limits on the first X-Forwarded-For entry: make it the visitor's real IP.
  headers.set("X-Forwarded-For", request.headers.get("CF-Connecting-IP") || "");
  headers.set("X-Forwarded-Proto", "https");
  headers.set("X-Forwarded-Host", url.host);
  if (env.PROXY_SECRET) headers.set("X-Proxy-Secret", env.PROXY_SECRET);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  try {
    return await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      redirect: "manual",
    });
  } catch {
    return Response.json({ detail: "The SafariAI API is not reachable right now. Try again in a minute." }, { status: 502 });
  }
}
