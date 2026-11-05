import { LANGUAGES, format, formatDate } from "../i18n";
import { isAdminSignedIn } from "../storage";

function freshness(status) {
  const sources = status?.sources || [];
  const synced = sources.filter((source) => source.last_success);
  if (!synced.length) return null;
  const tanapa =
    synced.find((source) => /tariff/i.test(`${source.id} ${source.name}`)) ||
    synced.find((source) => /tanapa/i.test(`${source.id} ${source.name}`)) ||
    synced[0];
  return tanapa.last_success;
}

export default function Header({ t, lang, onLanguage, status }) {
  const synced = freshness(status);
  return (
    <header className="site-header">
      <a className="brand" href="/">
        <img src="/brand/logo.png" alt="" />
        <span>
          <strong>SafariAI</strong>
          <small>{t.tagline}</small>
        </span>
      </a>
      <div className="header-tools">
        {synced ? (
          <span className="fresh-badge" title={synced}>
            <i aria-hidden="true" />
            {format(t.synced, { date: formatDate(synced, lang) })}
          </span>
        ) : null}
        <div className="lang-toggle" role="group" aria-label={t.language}>
          {LANGUAGES.map((code) => (
            <button key={code} type="button" aria-pressed={lang === code} onClick={() => onLanguage(code)}>
              {code.toUpperCase()}
            </button>
          ))}
        </div>
        {/* Visitors never see a way into admin; a signed-in admin gets a link back to the dashboard. */}
        {isAdminSignedIn() ? (
          <a className="header-link" href="/admin">
            {t.admin}
          </a>
        ) : null}
      </div>
    </header>
  );
}
