import { useEffect, useRef } from "react";
import { format, formatDate } from "../i18n";

function citationNumber(citation, index) {
  return citation.n ?? index + 1;
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
            <h2 id="sources-title" className="display">
              {t.sources}
            </h2>
            <p>{t.sourcesSub}</p>
          </div>
          <button ref={closeRef} type="button" className="icon-button light" onClick={onClose} aria-label={t.close}>
            ✕
          </button>
        </header>
        {citations.length ? (
          <ol className="source-list" ref={listRef}>
            {citations.map((citation, index) => {
              const number = citationNumber(citation, index);
              const window =
                citation.effective_from || citation.effective_until
                  ? format(t.effective, {
                      from: formatDate(citation.effective_from, lang) || "—",
                      to: formatDate(citation.effective_until, lang) || "—",
                    })
                  : "";
              return (
                <li
                  key={`${citation.document_id || "source"}-${number}`}
                  data-cite={number}
                  className={number === focus ? "is-focused" : ""}
                >
                  <span className="source-number">{number}</span>
                  <div>
                    <h3>{citation.title || citation.document_id}</h3>
                    <p className="source-meta">
                      {citation.organization ? <span>{citation.organization}</span> : null}
                      {citation.authority ? <span className="badge badge-small">{citation.authority}</span> : null}
                      {citation.status && citation.status !== "pointer" ? (
                        <span className={`badge badge-small ${citation.status === "current" ? "badge-ok" : "badge-warn"}`}>
                          {citation.status}
                        </span>
                      ) : null}
                    </p>
                    {window ? <p className="source-window">{window}</p> : null}
                    {citation.excerpt ? <blockquote>{citation.excerpt}</blockquote> : null}
                    {citation.source_url && /^https?:\/\//.test(citation.source_url) ? (
                      <a href={citation.source_url} target="_blank" rel="noopener noreferrer">
                        {t.openSource} ↗
                      </a>
                    ) : null}
                  </div>
                </li>
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
