// SafariAI admin dashboard: insights, the question log, feedback, TANAPA data and site management.
import { useEffect, useState } from "react";
import { AuthError, checkSession, login, onAuthError, saveToken } from "./api";
import Documents from "./sections/Documents";
import Feedback from "./sections/Feedback";
import Fees from "./sections/Fees";
import Insights from "./sections/Insights";
import Overview from "./sections/Overview";
import Parks from "./sections/Parks";
import Questions from "./sections/Questions";
import Sources from "./sections/Sources";
import System from "./sections/System";
import "./admin.css";

const SECTIONS = [
  { id: "overview", label: "Overview", group: "Monitor", component: Overview, period: true },
  { id: "insights", label: "Insights", group: "Monitor", component: Insights, period: true },
  { id: "questions", label: "Questions", group: "Monitor", component: Questions, period: true },
  { id: "feedback", label: "Feedback", group: "Monitor", component: Feedback, period: true },
  { id: "parks", label: "Parks", group: "TANAPA data", component: Parks },
  { id: "fees", label: "Fees & tariffs", group: "TANAPA data", component: Fees },
  { id: "documents", label: "Documents", group: "Manage", component: Documents },
  { id: "sources", label: "Sources & sync", group: "Manage", component: Sources },
  { id: "system", label: "System & quality", group: "Manage", component: System },
];
const PERIODS = [
  [1, "Today"],
  [7, "Last 7 days"],
  [30, "Last 30 days"],
  [90, "Last 90 days"],
  [365, "Last 12 months"],
];

function sectionFromHash() {
  const [id, query = ""] = window.location.hash.replace(/^#\/?/, "").split("?");
  return { id: SECTIONS.some((item) => item.id === id) ? id : "overview", params: Object.fromEntries(new URLSearchParams(query)) };
}

export function go(id, params = {}) {
  const query = new URLSearchParams(params).toString();
  window.location.hash = `/${id}${query ? `?${query}` : ""}`;
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

export default function AdminApp() {
  const [route, setRoute] = useState(sectionFromHash);
  const [days, setDays] = useState(30);
  const [auth, setAuth] = useState({ state: "checking", message: "", tokenRequired: false });
  const [menuOpen, setMenuOpen] = useState(false);

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
    checkSession()
      .then((result) => setAuth({ state: "ok", message: "", tokenRequired: result.token_required }))
      .catch((error) =>
        setAuth((current) => (current.state === "signed-out" ? current : { state: "signed-out", message: error instanceof AuthError ? "" : error.message, tokenRequired: true })),
      );
  }, [auth.state]);

  if (auth.state === "checking") return <main className="dash-signin" aria-busy="true" />;
  if (auth.state === "signed-out") {
    return (
      <SignIn message={auth.message} onSignedIn={() => setAuth({ state: "checking", message: "", tokenRequired: true })} />
    );
  }

  const section = SECTIONS.find((item) => item.id === route.id);
  const Section = section.component;
  const groups = [...new Set(SECTIONS.map((item) => item.group))];

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
                <a key={item.id} href={`#/${item.id}`} aria-current={item.id === route.id ? "page" : undefined}>
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
      <div className="dash-main">
        <header className="dash-top">
          <button type="button" className="dash-menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((value) => !value)}>
            Menu
          </button>
          <div>
            <span className="dash-eyebrow">{section.group}</span>
            <h1>{section.label}</h1>
          </div>
          {section.period ? (
            <label className="dash-field dash-period">
              <span>Period</span>
              <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
                {PERIODS.map(([value, text]) => (
                  <option key={value} value={value}>
                    {text}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </header>
        <main className="dash-content">
          <Section days={days} params={route.params} go={go} />
        </main>
      </div>
    </div>
  );
}
