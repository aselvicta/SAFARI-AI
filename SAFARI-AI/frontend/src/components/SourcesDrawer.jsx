import { useEffect, useRef, useState } from "react";
import { format, formatDate } from "../i18n";

// Excerpts longer than this start clamped to a few lines, with a toggle.
const LONG_EXCERPT = 240;

function citationNumber(citation, index) {
  return citation.n ?? index + 1;
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function Source({ citation, number, focused, t, lang }) {
  const [expanded, setExpanded] = useState(false);
  const window =
    citation.effective_from || citation.effective_until
      ? format(t.effective, {
          from: formatDate(citation.effective_from, lang) || "?",
          to: formatDate(citation.effective_until, lang) || "?",
        })
      : "";
  const meta = [citation.organization, citation.authority].filter(Boolean);
  const status = citation.status && citation.status !== "pointer" ? citation.status : null;
  const excerpt = citation.excerpt || "";
  const long = excerpt.length > LONG_EXCERPT;
  const link = citation.source_url && /^https?:\/\//.test(citation.source_url) ? citation.source_url : null;

  return (
    <li data-cite={number} className={focused ? "is-focused" : ""}>
      <span className="source-number" aria-hidden="true">
        {number}
      </span>
      <div className="source-body">
        <h3>
          <span className="visually-hidden">{number}. </span>
          {citation.title || citation.document_id}
        </h3>
        {meta.length || status ? (
          <p className="source-meta">
            {meta.map((item) => (
              <span key={item}>{item}</span>
            ))}
            {status ? <span className={`source-status ${status === "current" ? "ok" : "warn"}`}>{status}</span> : null}
          </p>
        ) : null}
        {window ? <p className="source-window">{window}</p> : null}
        {excerpt ? <p className={`source-excerpt ${long && !expanded ? "clamped" : ""}`}>{excerpt}</p> : null}
        {long || link ? (
          <div className="source-actions">
            {link ? (
              <a className="source-link" href={link} target="_blank" rel="noopener noreferrer" aria-label={`${t.openSource}: ${hostOf(link)}`}>
                {hostOf(link) || t.openSource} ↗
              </a>
            ) : null}
            {long ? (
              <button type="button" className="source-more" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
                {expanded ? t.showLess : t.showMore}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

export default function SourcesDrawer({ open, citations, focus, t, lang, onClose }) {
  const closeRef = useRef(null);
  const listRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement;
    closeRef.current?.focus();
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open || focus == null) return;
    const target = listRef.current?.querySelector(`[data-cite="${focus}"]`);
    target?.scrollIntoView({ block: "nearest" });
  }, [open, focus]);

  if (!open) return null;

  return (
    <div className="drawer-layer">
      <button type="button" className="drawer-scrim" aria-label={t.close} onClick={onClose} tabIndex={-1} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="sources-title">
        <header className="drawer-head">
          <div>
            <h2 id="sources-title">{t.sources}</h2>
            <p>
              {citations.length ? `${format(t.sourcesCount, { n: citations.length })} · ` : ""}
              {t.sourcesSub}
            </p>
          </div>
          <button ref={closeRef} type="button" className="drawer-close" onClick={onClose} aria-label={t.close}>
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </header>
        {citations.length ? (
          <ol className="source-list" ref={listRef}>
            {citations.map((citation, index) => {
              const number = citationNumber(citation, index);
              return (
                <Source
                  key={`${citation.document_id || "source"}-${number}`}
                  citation={citation}
                  number={number}
                  focused={number === focus}
                  t={t}
                  lang={lang}
                />
              );
            })}
          </ol>
        ) : (
          <p className="drawer-empty">{t.noSources}</p>
        )}
      </aside>
    </div>
  );
}
