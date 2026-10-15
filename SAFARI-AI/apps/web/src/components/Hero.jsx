import { useState } from "react";

const PREFERRED = ["serengeti", "tarangire", "kilimanjaro", "ruaha"];

function heroImage(parks) {
  const withImage = parks.filter((park) => park.image_url);
  for (const slug of PREFERRED) {
    const match = withImage.find((park) => park.slug?.toLowerCase() === slug);
    if (match) return match;
  }
  return withImage[0] || null;
}

export default function Hero({ t, parks, onAsk }) {
  const [draft, setDraft] = useState("");
  const featured = heroImage(parks);

  function submit(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    onAsk(text);
    setDraft("");
  }

  return (
    <section className="hero" aria-labelledby="hero-title">
      {featured ? <img className="hero-photo" src={featured.image_url} alt="" fetchPriority="high" /> : null}
      <div className="hero-shade" aria-hidden="true" />
      <div className="hero-inner">
        <p className="eyebrow light">{t.heroEyebrow}</p>
        <h1 id="hero-title" className="hero-title">
          <span className="accent">{t.heroAccent}</span>
          <span>{t.heroLine1}</span>
          <span className="indent">{t.heroLine2}</span>
        </h1>
        <p className="hero-sub">{t.heroSub}</p>
        <form className="hero-ask" onSubmit={submit}>
          <label className="sr" htmlFor="hero-input">
            {t.askPlaceholder}
          </label>
          <input
            id="hero-input"
            value={draft}
            placeholder={t.askPlaceholder}
            onChange={(event) => setDraft(event.target.value)}
            autoComplete="off"
          />
          <button type="submit" className="primary-button">
            {t.ask} <span aria-hidden="true">↘</span>
          </button>
        </form>
        <div className="hero-chips">
          {t.suggestions.map((item) => (
            <button key={item} type="button" className="chip on-dark" onClick={() => onAsk(item)}>
              {item}
            </button>
          ))}
        </div>
        {featured ? <p className="hero-credit">{featured.name}</p> : null}
      </div>
    </section>
  );
}
