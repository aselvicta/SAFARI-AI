import { useState } from "react";
import Blocks from "./Blocks";
import Markdown from "./Markdown";
import { format } from "../i18n";

function StatusLine({ label }) {
  return (
    <p className="status-line" role="status">
      <span className="status-dots" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      {label}
    </p>
  );
}

function plainText(markdown) {
  return (markdown || "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, "$1 ($2)")
    .replace(/\[(\d{1,2})\]/g, "[$1]");
}

function AssistantFooter({ message, t, onSources, onFeedback }) {
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState(0);
  const payload = message.payload || {};
  const citations = payload.citations || [];
  const confidence = payload.confidence_label;

  async function copy() {
    try {
      await navigator.clipboard.writeText(plainText(message.text));
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  function rate(value) {
    if (rating) return;
    setRating(value);
    onFeedback(message, value);
  }

  return (
    <footer className="message-footer">
      {confidence ? (
        <span className={`pill pill-${confidence.toLowerCase()}`}>{t.confidence[confidence] || confidence}</span>
      ) : null}
      {citations.length ? (
        <button type="button" className="ghost-button" onClick={() => onSources(citations, null)}>
          {citations.length === 1 ? t.sourceOne : format(t.sourcesCount, { n: citations.length })}
        </button>
      ) : null}
      <span className="footer-spacer" />
      <button type="button" className="icon-button" onClick={copy} aria-label={t.copy} title={t.copy}>
        {copied ? "✓" : "⧉"}
      </button>
      <button
        type="button"
        className={`icon-button${rating === 1 ? " is-active" : ""}`}
        onClick={() => rate(1)}
        aria-label={t.helpful}
        title={rating ? t.thanks : t.helpful}
        aria-pressed={rating === 1}
        disabled={Boolean(rating)}
      >
        ▲
      </button>
      <button
        type="button"
        className={`icon-button${rating === -1 ? " is-active" : ""}`}
        onClick={() => rate(-1)}
        aria-label={t.notHelpful}
        title={rating ? t.thanks : t.notHelpful}
        aria-pressed={rating === -1}
        disabled={Boolean(rating)}
      >
        ▼
      </button>
    </footer>
  );
}

export default function Message({ message, t, lang, onAsk, onSources, onFeedback, isLatest }) {
  if (message.role === "user") {
    return (
      <article className="message user">
        <p>{message.text}</p>
      </article>
    );
  }

  const payload = message.payload;
  const citations = payload?.citations || [];
  const openCitation = (number) => onSources(citations, number);
  const abstained = Boolean(payload?.abstained);

  return (
    <article className={`message assistant${abstained ? " is-abstained" : ""}${message.error ? " is-error" : ""}`}>
      <img className="avatar" src="/brand/logo.png" alt="" />
      <div className="message-body" aria-live={message.streaming ? "polite" : undefined} aria-busy={message.streaming}>
        {abstained ? <p className="abstain-tag">{t.officialNeeded}</p> : null}
        {message.streaming && !message.text ? <StatusLine label={message.status || t.thinking} /> : null}
        <Markdown text={message.text} onCite={openCitation} />
        {message.streaming && message.text && message.status ? <StatusLine label={message.status} /> : null}
        {payload ? <Blocks blocks={payload.blocks} t={t} lang={lang} onAsk={onAsk} /> : null}
        {payload && !message.streaming ? (
          <AssistantFooter message={message} t={t} onSources={onSources} onFeedback={onFeedback} />
        ) : null}
        {isLatest && payload?.follow_ups?.length && !message.streaming ? (
          <div className="follow-ups">
            {payload.follow_ups.map((item) => (
              <button key={item} type="button" className="chip" onClick={() => onAsk(item)}>
                {item}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}
