import { useCallback, useEffect, useRef, useState } from "react";
import { askStream, downloadBriefing, fetchParks, fetchStatus, sendFeedback } from "./api";
import { strings } from "./i18n";
import { newSessionId, readJson, writeJson } from "./storage";
import Admin from "./components/Admin";
import Chat from "./components/Chat";
import Header from "./components/Header";
import Hero from "./components/Hero";
import ParkExplorer from "./components/ParkExplorer";
import SourcesDrawer from "./components/SourcesDrawer";
import TripPanel, { EMPTY_TRIP, visitorClass } from "./components/TripPanel";

const KEYS = { lang: "safari.lang", session: "safari.session", trip: "safari.trip" };

function initialLanguage() {
  const saved = readJson(KEYS.lang, null);
  if (saved === "en" || saved === "sw") return saved;
  return (navigator.language || "").toLowerCase().startsWith("sw") ? "sw" : "en";
}

function initialSession() {
  const saved = readJson(KEYS.session, null);
  if (saved) return saved;
  const created = newSessionId();
  writeJson(KEYS.session, created);
  return created;
}

function toCount(value) {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Math.round(number) : null;
}

function buildProfile(trip, lang) {
  const passport = trip.passport.trim();
  return {
    passport,
    origin: trip.origin.trim(),
    days: toCount(trip.days),
    adults: toCount(trip.adults),
    children: trip.childAges.length,
    child_ages: trip.childAges,
    visitor_class: visitorClass(passport),
    language: lang,
  };
}

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

let messageCounter = 0;
const nextId = () => `m${Date.now().toString(36)}${(messageCounter++).toString(36)}`;

export default function App() {
  const [lang, setLang] = useState(initialLanguage);
  const [sessionId, setSessionId] = useState(initialSession);
  const [trip, setTrip] = useState(() => ({ ...EMPTY_TRIP, ...readJson(KEYS.trip, {}) }));
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [parks, setParks] = useState([]);
  const [status, setStatus] = useState(null);
  const [drawer, setDrawer] = useState({ open: false, citations: [], focus: null });
  const [tripOpen, setTripOpen] = useState(false);
  const [lastParks, setLastParks] = useState([]);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const abortRef = useRef(null);
  const deskRef = useRef(null);
  const inputRef = useRef(null);
  const t = strings(lang);
  const isAdmin = window.location.pathname.replace(/\/+$/, "") === "/admin";

  useEffect(() => {
    document.documentElement.lang = lang;
    writeJson(KEYS.lang, lang);
  }, [lang]);

  useEffect(() => {
    writeJson(KEYS.trip, trip);
  }, [trip]);

  useEffect(() => {
    let alive = true;
    fetchParks().then((items) => alive && setParks(Array.isArray(items) ? items : []));
    fetchStatus().then((value) => alive && setStatus(value));
    return () => {
      alive = false;
    };
  }, []);

  // Shareable question links: /?q=Serengeti%20entry%20fees asks on load.
  const askedFromLink = useRef(false);
  useEffect(() => {
    if (askedFromLink.current || isAdmin) return;
    const question = new URLSearchParams(window.location.search).get("q");
    if (question && question.trim()) {
      askedFromLink.current = true;
      send(question.trim());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateMessage = useCallback((id, change) => {
    setMessages((current) =>
      current.map((message) => {
        if (message.id !== id) return message;
        return { ...message, ...(typeof change === "function" ? change(message) : change) };
      }),
    );
  }, []);

  function scrollToDesk() {
    deskRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  }

  async function send(text) {
    const question = (text || "").trim();
    if (!question || busy) return;
    const assistantId = nextId();
    setMessages((current) => [
      ...current,
      { id: nextId(), role: "user", text: question },
      { id: assistantId, role: "assistant", text: "", status: t.thinking, streaming: true },
    ]);
    setBusy(true);
    setTripOpen(false);
    scrollToDesk();

    const controller = new AbortController();
    abortRef.current = controller;
    const body = {
      question,
      session_id: sessionId,
      as_of: trip.date || undefined,
      language: lang,
      profile: buildProfile(trip, lang),
    };

    try {
      const payload = await askStream(body, {
        signal: controller.signal,
        onStatus: (label) => updateMessage(assistantId, { status: label }),
        onDelta: (chunk) => updateMessage(assistantId, (message) => ({ text: message.text + chunk })),
        onReset: () => updateMessage(assistantId, { text: "" }),
      });
      updateMessage(assistantId, { payload, text: payload.answer || "", streaming: false, status: "" });
      const slugs = (payload.recommended_parks || []).map((park) => park.slug).filter(Boolean);
      if (slugs.length) setLastParks(slugs);
    } catch (error) {
      if (error.name === "AbortError") {
        updateMessage(assistantId, (message) => ({
          text: message.text ? `${message.text}\n\n*${t.stopped}*` : t.stopped,
          streaming: false,
          status: "",
        }));
      } else {
        updateMessage(assistantId, { text: t.connectionError, streaming: false, status: "", error: true });
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  function newChat() {
    stop();
    const created = newSessionId();
    writeJson(KEYS.session, created);
    setSessionId(created);
    setMessages([]);
    setLastParks([]);
    inputRef.current?.focus();
  }

  const openSources = useCallback((citations, focus) => {
    setDrawer({ open: true, citations: citations || [], focus });
  }, []);
  const closeSources = useCallback(() => setDrawer((current) => ({ ...current, open: false })), []);

  function feedback(message, rating) {
    const index = messages.findIndex((item) => item.id === message.id);
    const question = [...messages.slice(0, index)].reverse().find((item) => item.role === "user")?.text || "";
    sendFeedback({ session_id: sessionId, question, answer: message.text, rating });
  }

  async function briefing() {
    setDownloading(true);
    setDownloadError("");
    const profile = buildProfile(trip, lang);
    try {
      await downloadBriefing({
        question: messages.filter((item) => item.role === "user").map((item) => item.text).join(". ") || "plan a visit",
        origin: profile.origin,
        parks: lastParks,
        days: profile.days,
        adults: profile.adults,
        children: profile.children,
        child_ages: profile.child_ages,
        passport: profile.passport,
        as_of: trip.date || undefined,
      });
    } catch {
      setDownloadError(t.pdfFailed);
    } finally {
      setDownloading(false);
    }
  }

  if (isAdmin) {
    return (
      <div className="app admin-app">
        <Header t={t} lang={lang} onLanguage={setLang} status={status} admin />
        <Admin lang={lang} />
      </div>
    );
  }

  return (
    <div className="app">
      <a className="skip-link" href="#desk">
        {t.deskTitle}
      </a>
      <Header t={t} lang={lang} onLanguage={setLang} status={status} />
      <main>
        <Hero t={t} parks={parks} onAsk={send} />
        <section className="workspace" id="desk" ref={deskRef} tabIndex={-1}>
          <Chat
            t={t}
            lang={lang}
            messages={messages}
            busy={busy}
            onSend={send}
            onStop={stop}
            onSources={openSources}
            onFeedback={feedback}
            onNewChat={newChat}
            inputRef={inputRef}
          />
          <TripPanel
            t={t}
            trip={trip}
            onChange={setTrip}
            onDownload={briefing}
            downloading={downloading}
            downloadError={downloadError}
            open={tripOpen}
            onClose={() => setTripOpen(false)}
          />
        </section>
        <ParkExplorer t={t} parks={parks} onAsk={send} />
      </main>
      <footer className="site-footer">
        <img src="/brand/arms.png" alt="" />
        <p>{t.footer}</p>
        <p className="footer-links">
          <a href="https://www.tanzaniaparks.go.tz/tourism/visitor-information/tariff" target="_blank" rel="noopener noreferrer">
            TANAPA tariffs ↗
          </a>
          <a href="https://visa.immigration.go.tz" target="_blank" rel="noopener noreferrer">
            Tanzania eVisa ↗
          </a>
        </p>
      </footer>
      <button
        type="button"
        className="trip-fab"
        onClick={() => setTripOpen(true)}
        aria-expanded={tripOpen}
        aria-controls="trip-title"
      >
        {t.tripToggle}
      </button>
      {tripOpen ? <button type="button" className="sheet-scrim" aria-label={t.close} onClick={() => setTripOpen(false)} /> : null}
      <SourcesDrawer
        open={drawer.open}
        citations={drawer.citations}
        focus={drawer.focus}
        t={t}
        lang={lang}
        onClose={closeSources}
      />
    </div>
  );
}
