import { useEffect, useRef, useState } from "react";
import Message from "./Message";

function Composer({ t, busy, onSend, onStop, inputRef }) {
  const [draft, setDraft] = useState("");

  function submit(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    onSend(text);
    setDraft("");
  }

  return (
    <form className="composer" onSubmit={submit}>
      <label className="sr" htmlFor="composer-input">
        {t.askPlaceholder}
      </label>
      <textarea
        id="composer-input"
        ref={inputRef}
        rows={1}
        value={draft}
        placeholder={t.askPlaceholder}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            event.currentTarget.form.requestSubmit();
          }
        }}
      />
      {busy ? (
        <button type="button" className="secondary-button" onClick={onStop}>
          {t.stop}
        </button>
      ) : (
        <button type="submit" className="primary-button" disabled={!draft.trim()}>
          {t.send}
        </button>
      )}
    </form>
  );
}

function EmptyState({ t, onAsk }) {
  return (
    <div className="chat-empty">
      <img src="/brand/elephant.svg" alt="" />
      <h3>{t.emptyTitle}</h3>
      <p>{t.emptyBody}</p>
      <div className="follow-ups centered">
        {t.suggestions.map((item) => (
          <button key={item} type="button" className="chip" onClick={() => onAsk(item)}>
            {item}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Chat({ t, lang, messages, busy, onSend, onStop, onSources, onFeedback, onNewChat, inputRef }) {
  const threadRef = useRef(null);
  const pinnedRef = useRef(true);

  useEffect(() => {
    const thread = threadRef.current;
    if (thread && pinnedRef.current) thread.scrollTop = thread.scrollHeight;
  }, [messages]);

  function trackScroll() {
    const thread = threadRef.current;
    if (!thread) return;
    pinnedRef.current = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
  }

  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");

  return (
    <section className="chat" aria-label={t.deskTitle}>
      <header className="chat-head">
        <div>
          <h2 className="display">{t.deskTitle}</h2>
          <p>{t.deskSub}</p>
        </div>
        {messages.length ? (
          <button type="button" className="ghost-button light" onClick={onNewChat}>
            {t.newChat}
          </button>
        ) : null}
      </header>
      <div className="thread" ref={threadRef} onScroll={trackScroll}>
        {messages.length ? (
          messages.map((message) => (
            <Message
              key={message.id}
              message={message}
              t={t}
              lang={lang}
              onAsk={onSend}
              onSources={onSources}
              onFeedback={onFeedback}
              isLatest={message === lastAssistant}
            />
          ))
        ) : (
          <EmptyState t={t} onAsk={onSend} />
        )}
      </div>
      <Composer t={t} busy={busy} onSend={onSend} onStop={onStop} inputRef={inputRef} />
    </section>
  );
}
