// SafariAI admin dashboard: insights, the question log, feedback, TANAPA data and site management.
import { Suspense, lazy, useEffect, useState } from "react";
import { AuthError, checkSession, login, onAuthError, queries, saveToken } from "./api";
import { invalidate, lastLoaded, onLoaded, prefetch, refreshAll } from "./data";
import { ago } from "./format";
import { Segmented, Skeleton } from "./ui";
import "./admin.css";

// Each section is its own chunk, loaded on first visit (and prefetched when its link is hovered).
const load = {
  overview: () => import("./sections/Overview"),
  insights: () => import("./sections/Insights"),
  questions: () => import("./sections/Questions"),
  feedback: () => import("./sections/Feedback"),
  parks: () => import("./sections/Parks"),
  fees: () => import("./sections/Fees"),
  documents: () => import("./sections/Documents"),
  sources: () => import("./sections/Sources"),
  system: () => import("./sections/System"),
};

// `data` lists the queries a section opens with, so hovering its link can warm them.
const SECTIONS = [
  { id: "overview", label: "Overview", group: "Monitor", period: true, skeleton: "overview", data: (days) => [queries.overview(days)] },
  { id: "insights", label: "Insights", group: "Monitor", period: true, skeleton: "insights", data: (days) => [queries.overview(days)] },
  { id: "questions", label: "Questions", group: "Monitor", period: true, skeleton: "table", data: (days) => [queries.questions({ days, limit: 50, offset: 0 }), queries.parks()] },
  { id: "feedback", label: "Feedback", group: "Monitor", period: true, skeleton: "table", data: (days) => [queries.feedback({ days, limit: 25, offset: 0 })] },
  { id: "parks", label: "Parks", group: "TANAPA data", skeleton: "cards", data: () => [queries.inventory()] },
  { id: "fees", label: "Fees & tariffs", group: "TANAPA data", skeleton: "table", data: () => [queries.inventory(), queries.parks()] },
  { id: "documents", label: "Documents", group: "Manage", skeleton: "table", data: () => [queries.documents(), queries.inventory()] },
  { id: "sources", label: "Sources & sync", group: "Manage", skeleton: "table", data: () => [queries.status(), queries.harvests()] },
  { id: "system", label: "System & quality", group: "Manage", skeleton: "cards", data: () => [queries.system(), queries.evaluation()] },
].map((section) => ({ ...section, component: lazy(load[section.id]) }));

const PERIODS = [
  [1, "Today", "Today"],
  [7, "7D", "Last 7 days"],
  [30, "30D", "Last 30 days"],
  [90, "90D", "Last 90 days"],
  [365, "12M", "Last 12 months"],
];

// 16px line icons, drawn on a 24px grid.
const ICONS = {
  overview: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
  insights: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  questions: "M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z",
  feedback: "M7 11v9H4v-9zM7 11l4-8a2 2 0 0 1 3 2l-1 5h6a2 2 0 0 1 2 2l-2 7a2 2 0 0 1-2 1H7",
  parks: "M3 20l6-11 4 7 3-4 5 8zM15 6a2 2 0 1 0 0-.01",
  fees: "M3 12V4h8l10 10-8 8zM7.5 8a.5.5 0 1 0 0-.01",
  documents: "M6 2h9l5 5v15H6zM14 2v6h6M9 13h8M9 17h8",
  sources: "M20 7a9 9 0 0 0-15.5 1M4 4v4h4M4 17a9 9 0 0 0 15.5-1M20 20v-4h-4",
  system: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7 7 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z",
};

function Icon({ name }) {
  return (
    <svg className="nav-icon" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={ICONS[name]} />
    </svg>
  );
}

function sectionFromHash() {
  const [id, query = ""] = window.location.hash.replace(/^#\/?/, "").split("?");
  return { id: SECTIONS.some((item) => item.id === id) ? id : "overview", params: Object.fromEntries(new URLSearchParams(query)) };
}

export function go(id, params = {}) {
  const query = new URLSearchParams(params).toString();
  window.location.hash = `/${id}${query ? `?${query}` : ""}`;
}

const idle = (callback) => (window.requestIdleCallback ? window.requestIdleCallback(callback, { timeout: 2500 }) : setTimeout(callback, 600));

function warmSection(section, days) {
  load[section.id]().catch(() => {});
  section.data(days).forEach((query) => prefetch(query));
}

function SignIn({ message, onSignedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <main className="dash-signin">
      <form
        className="dash-card"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          try {
            await login(username.trim(), password);
            onSignedIn();
          } catch (failure) {
            setError(failure.message);
            setPassword("");
          } finally {
            setBusy(false);
          }
        }}
      >
        <img src="/brand/logo.png" alt="" width="56" height="56" />
        <h1>SafariAI admin</h1>
        <p role={error ? "alert" : undefined}>{error || message || "Sign in with your admin username and password."}</p>
        <label className="dash-field">
          <span>Username</span>
          <input type="text" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} autoFocus required />
        </label>
        <label className="dash-field">
          <span>Password</span>
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        </label>
        <button type="submit" className="dash-button primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <a href="/" className="dash-link">
          ← Back to the visitor desk
        </a>
      </form>
    </main>
  );
}

/** "Updated 2 min ago", ticking, from the last query that finished loading. */
function Freshness({ refreshing, onRefresh }) {
  const [at, setAt] = useState(lastLoaded);
  const [, setNow] = useState(0);
  useEffect(() => onLoaded(setAt), []);
  useEffect(() => {
    const timer = setInterval(() => setNow((value) => value + 1), 30_000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="dash-freshness">
      <span className="dash-updated" aria-live="polite">
        {refreshing ? "Refreshing…" : at ? `Updated ${ago(new Date(at).toISOString())}` : ""}
      </span>
      <button type="button" className="dash-button dash-refresh" onClick={onRefresh} disabled={refreshing} title="Reload the numbers on this page">
        <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d={ICONS.sources} />
        </svg>
        Refresh
      </button>
    </div>
  );
}

export default function AdminApp() {
  const [route, setRoute] = useState(sectionFromHash);
  const [days, setDays] = useState(() => Number(sessionStorage.getItem("safari.adminDays")) || 30);
  const [auth, setAuth] = useState({ state: "checking", message: "", tokenRequired: false });
  const [menuOpen, setMenuOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    document.title = "Admin · SafariAI Tanzania";
    const update = () => {
      setRoute(sectionFromHash());
      setMenuOpen(false);
    };
    window.addEventListener("hashchange", update);
    onAuthError((message) => setAuth({ state: "signed-out", message: message || "", tokenRequired: true }));
    return () => window.removeEventListener("hashchange", update);
  }, []);

  useEffect(() => {
    if (auth.state !== "checking") return;
    // Start the first section's data with the session check instead of after it.
    sectionFor(route.id).data(days).forEach((query) => prefetch(query));
    checkSession()
      .then((result) => setAuth({ state: "ok", message: "", tokenRequired: result.token_required }))
      .catch((error) =>
        setAuth((current) => (current.state === "signed-out" ? current : { state: "signed-out", message: error instanceof AuthError ? "" : error.message, tokenRequired: true })),
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.state]);

  // Once the first page is up, warm the pages people open next.
  useEffect(() => {
    if (auth.state !== "ok") return;
    idle(() => ["overview", "insights", "questions", "feedback"].forEach((id) => warmSection(sectionFor(id), days)));
  }, [auth.state, days]);

  useEffect(() => {
    sessionStorage.setItem("safari.adminDays", String(days));
  }, [days]);

  if (auth.state === "checking") return <main className="dash-signin" aria-busy="true" />;
  if (auth.state === "signed-out") {
    return <SignIn message={auth.message} onSignedIn={() => setAuth({ state: "checking", message: "", tokenRequired: true })} />;
  }

  const section = sectionFor(route.id);
  const Section = section.component;
  const groups = [...new Set(SECTIONS.map((item) => item.group))];

  function reloadAll() {
    setRefreshing(true);
    const stop = onLoaded(() => {
      stop();
      setRefreshing(false);
    });
    refreshAll();
    setTimeout(() => setRefreshing(false), 15_000);
  }

  return (
    <div className="dash">
      <aside className={`dash-side ${menuOpen ? "open" : ""}`}>
        <a href="/" className="dash-brand">
          <img src="/brand/logo.png" alt="" width="34" height="34" />
          <span>
            <strong>SafariAI</strong>
            <small>Admin</small>
          </span>
        </a>
        <nav aria-label="Dashboard">
          {groups.map((group) => (
            <div key={group} className="dash-nav-group">
              <span className="dash-nav-title">{group}</span>
              {SECTIONS.filter((item) => item.group === group).map((item) => (
                <a
                  key={item.id}
                  href={`#/${item.id}`}
                  aria-current={item.id === route.id ? "page" : undefined}
                  onPointerEnter={() => warmSection(item, days)}
                  onFocus={() => warmSection(item, days)}
                >
                  <Icon name={item.id} />
                  {item.label}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <div className="dash-side-foot">
          <a href="/" className="dash-link">
            Open visitor desk ↗
          </a>
          {auth.tokenRequired ? (
            <button
              type="button"
              className="dash-link"
              onClick={() => {
                saveToken("");
                invalidate();
                setAuth({ state: "signed-out", message: "Signed out.", tokenRequired: true });
              }}
            >
              Sign out
            </button>
          ) : (
            <span className="dash-side-note">Local access, no token set</span>
          )}
        </div>
      </aside>
      {menuOpen ? <button type="button" className="dash-scrim" aria-label="Close menu" onClick={() => setMenuOpen(false)} /> : null}
      <div className="dash-main">
        <header className="dash-top">
          <button type="button" className="dash-menu" aria-expanded={menuOpen} aria-label="Menu" onClick={() => setMenuOpen((value) => !value)}>
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="dash-title">
            <span className="dash-eyebrow">{section.group}</span>
            <h1>{section.label}</h1>
          </div>
          <div className="dash-top-tools">
            {section.period ? <Segmented label="Period" options={PERIODS} value={days} onChange={setDays} /> : null}
            <Freshness refreshing={refreshing} onRefresh={reloadAll} />
          </div>
        </header>
        <main className="dash-content">
          <Suspense fallback={<Skeleton layout={section.skeleton} />}>
            <Section days={days} params={route.params} go={go} />
          </Suspense>
        </main>
      </div>
    </div>
  );
}

function sectionFor(id) {
  return SECTIONS.find((item) => item.id === id) || SECTIONS[0];
}
