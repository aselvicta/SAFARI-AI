import ParkCard from "./ParkCard";
import { format, formatDate, formatNumber } from "../i18n";

const VISITOR_ORDER = ["non_resident", "expatriate", "eac", "resident"];
const AGE_ORDER = ["adult", "child_5_15", "student", "under_5", "any"];

function rank(order, key) {
  const position = order.indexOf(key);
  return position < 0 ? order.length : position;
}

function label(map, key) {
  return (map && map[key]) || key || "";
}

function Usd({ value, t }) {
  if (value === null || value === undefined || value === "" || Number(value) === 0) return null;
  return <span className="usd">{format(t.approxUsd, { n: formatNumber(value, 2) })}</span>;
}

function FeesBlock({ block, t, lang }) {
  const groups = new Map();
  for (const row of block.rows || []) {
    const key = row.visitor || "other";
    if (!groups.has(key)) groups.set(key, { label: row.visitor_label || label(t.labels.visitor, key), rows: [] });
    groups.get(key).rows.push(row);
  }
  const ordered = [...groups.entries()].sort(([a], [b]) => rank(VISITOR_ORDER, a) - rank(VISITOR_ORDER, b));
  const hasUsd = (block.rows || []).some((row) => Number(row.amount_usd) > 0);

  return (
    <section className="block block-fees" aria-label={t.fees}>
      <header className="block-head">
        <div>
          <p className="eyebrow">{t.fees}</p>
          <h4>{block.park_name || block.park_slug}</h4>
        </div>
        {block.in_force === undefined ? null : (
          <span className={`badge ${block.in_force ? "badge-ok" : "badge-warn"}`}>
            {block.in_force ? t.inForce : t.notInForce}
          </span>
        )}
      </header>
      {block.valid_from || block.valid_until ? (
        <p className="block-meta">
          {format(t.valid, { from: formatDate(block.valid_from, lang) || "?", to: formatDate(block.valid_until, lang) || "?" })}
        </p>
      ) : null}
      {ordered.map(([key, group]) => (
        <div className="fee-group" key={key}>
          <h5>{group.label}</h5>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">{t.item}</th>
                  <th scope="col">{t.season}</th>
                  <th scope="col" className="num">
                    {t.amount}
                  </th>
                </tr>
              </thead>
              <tbody>
                {[...group.rows]
                  .sort((a, b) => rank(AGE_ORDER, a.age) - rank(AGE_ORDER, b.age))
                  .map((row, index) => (
                    <tr key={`${key}-${index}`}>
                      <td>
                        <span className="fee-item">{row.item || row.category}</span>
                        {row.age && row.age !== "any" ? (
                          <span className="fee-age">{label(t.labels.age, row.age)}</span>
                        ) : null}
                      </td>
                      <td>{label(t.labels.season, row.season)}</td>
                      <td className="num">
                        <strong>{formatNumber(row.amount_tzs)}</strong>
                        <Usd value={row.amount_usd} t={t} />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      {block.notes?.length || hasUsd ? (
        <ul className="block-notes">
          {(block.notes || []).map((note, index) => (
            <li key={index}>{note}</li>
          ))}
          {hasUsd ? <li>{t.usdNote}</li> : null}
        </ul>
      ) : null}
      {block.source_url ? (
        <a className="block-link" href={block.source_url} target="_blank" rel="noopener noreferrer">
          {t.officialPage} ↗
        </a>
      ) : null}
    </section>
  );
}

function ParksBlock({ block, t, onAsk }) {
  const parks = block.parks || [];
  if (!parks.length) return null;
  return (
    <section className="block block-parks" aria-label={t.parks}>
      <div className="park-strip">
        {parks.map((park) => (
          <ParkCard
            key={park.slug}
            park={park}
            t={t}
            compact
            onPlan={(chosen) => onAsk(format(t.askAbout, { name: chosen.name }))}
          />
        ))}
      </div>
    </section>
  );
}

function EstimateBlock({ block, t }) {
  return (
    <section className="block block-estimate" aria-label={t.estimate}>
      <header className="block-head">
        <div>
          <p className="eyebrow">{t.estimate}</p>
          {block.park_name || block.park_slug ? <h4>{block.park_name || block.park_slug}</h4> : null}
        </div>
        {block.days ? <span className="badge">{block.days} d</span> : null}
      </header>
      <ul className="receipt">
        {(block.lines || []).map((line, index) => (
          <li key={index}>
            <div className="receipt-label">
              <span>{line.label}</span>
              <small>
                {formatNumber(line.qty)} × {formatNumber(line.days || block.days || 1)} {t.daysShort || "days"} × TZS {formatNumber(line.unit_tzs)}
              </small>
            </div>
            <span className="receipt-amount">{formatNumber(line.total_tzs)}</span>
          </li>
        ))}
        <li className="receipt-total">
          <span>{t.total}</span>
          <span className="receipt-amount">
            <strong>TZS {formatNumber(block.total_tzs)}</strong>
            <Usd value={block.total_usd} t={t} />
          </span>
        </li>
      </ul>
      {block.excludes?.length ? (
        <div className="block-notes">
          <p className="eyebrow">{t.excludes}</p>
          <ul>
            {block.excludes.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function VisaBlock({ block, t }) {
  return (
    <section className="block block-visa" aria-label={t.visa}>
      <header className="block-head">
        <div>
          <p className="eyebrow">{t.visa}</p>
          <h4>{block.country || block.passport}</h4>
        </div>
        {block.visa ? <span className="badge">{block.visa}</span> : null}
      </header>
      <dl className="rows">
        {block.fee ? (
          <div>
            <dt>Fee</dt>
            <dd>{block.fee}</dd>
          </div>
        ) : null}
        {(block.lines || []).map((line, index) => (
          <div key={index}>
            <dt>{line.label}</dt>
            <dd>{line.value}</dd>
          </div>
        ))}
      </dl>
      {block.source_url ? (
        <a className="block-link" href={block.source_url} target="_blank" rel="noopener noreferrer">
          {t.officialPage} ↗
        </a>
      ) : null}
    </section>
  );
}

const GROUPS = [
  ["live", "groupLive", "groupLiveNote"],
  ["official", "groupOfficial", "groupOfficialNote"],
  ["estimate", "groupEstimate", "groupEstimateNote"],
];

function TripBudgetBlock({ block, t, lang }) {
  const route = block.route || {};
  const fx = block.fx || {};
  return (
    <section className="block block-budget" aria-label={t.budget}>
      <header className="block-head">
        <div>
          <p className="eyebrow">{t.budget}</p>
          <h4>{block.park_name}</h4>
        </div>
        <span className="badge">
          {block.days} d · {block.people}
        </span>
      </header>
      <p className="block-meta">
        {format(t.budgetRoute, { from: block.origin, to: block.arrival?.name, km: formatNumber(route.km) })}
        {route.hours ? format(t.budgetHours, { h: formatNumber(route.hours, 1) }) : ""}
      </p>
      {GROUPS.map(([key, title, note]) => {
        const lines = (block.lines || []).filter((line) => line.group === key);
        if (!lines.length) return null;
        return (
          <div className={`budget-group budget-${key}`} key={key}>
            <h5>
              <span className={`dot dot-${key}`} aria-hidden="true" />
              {t[title]} <small>{t[note]}</small>
            </h5>
            <ul className="receipt">
              {lines.map((line, index) => (
                <li key={index}>
                  <div className="receipt-label">
                    <span>{line.label}</span>
                    <small>{line.detail}</small>
                  </div>
                  <span className="receipt-amount">
                    {formatNumber(line.total_tzs)}
                    <Usd value={line.usd} t={t} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      <ul className="receipt">
        {block.buffer_tzs ? (
          <li>
            <div className="receipt-label">
              <span>{format(t.buffer, { p: Math.round((block.buffer_rate || 0) * 100) })}</span>
            </div>
            <span className="receipt-amount">{formatNumber(block.buffer_tzs)}</span>
          </li>
        ) : null}
        <li className="receipt-total">
          <span>
            {t.total}
            <small className="per-person">
              {" "}
              TZS {formatNumber(block.per_person_tzs)} {t.perPerson}
            </small>
          </span>
          <span className="receipt-amount">
            <strong>TZS {formatNumber(block.total_tzs)}</strong>
            <Usd value={block.total_usd} t={t} />
            {block.currency ? (
              <span className="usd">
                {block.currency.code} {formatNumber(block.currency.total, 2)}
              </span>
            ) : null}
          </span>
        </li>
      </ul>
      <p className={`fx-line${fx.live ? "" : " is-stale"}`}>
        {fx.live
          ? format(t.fxLine, { rate: formatNumber(fx.usd, 2), date: formatDate(fx.date, lang) || fx.date })
          : format(t.fxFallback, { source: fx.source })}
      </p>
      {block.hotels?.some((hotel) => hotel.usd_per_night) ? (
        <div className="budget-hotels">
          <p className="eyebrow">{t.hotelsFound}</p>
          <ul>
            {block.hotels
              .filter((hotel) => hotel.usd_per_night)
              .map((hotel) => (
                <li key={hotel.key}>
                  {hotel.url ? (
                    <a href={hotel.url} target="_blank" rel="noopener noreferrer">
                      {hotel.name}
                    </a>
                  ) : (
                    hotel.name
                  )}
                  <span>
                    {format(t.perNight, { n: formatNumber(hotel.usd_per_night) })}
                    {hotel.km !== undefined && hotel.km !== null ? ` · ${formatNumber(hotel.km)} km` : ""}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      ) : null}
      {block.excluded?.length || block.notes?.length ? (
        <div className="block-notes">
          {block.excluded?.length ? (
            <>
              <p className="eyebrow">{t.excludes}</p>
              <ul>
                {block.excluded.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </>
          ) : null}
          {block.notes?.length ? (
            <ul>
              {block.notes.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {block.sources?.length ? (
        <p className="budget-sources">
          {t.budgetSources}:{" "}
          {block.sources.map((source, index) => (
            <span key={source.key}>
              {index ? " · " : ""}
              <a href={source.url} target="_blank" rel="noopener noreferrer">
                {source.title}
              </a>
              {source.live ? <em> ({t.live})</em> : null}
            </span>
          ))}
        </p>
      ) : null}
    </section>
  );
}

const RENDERERS = { fees: FeesBlock, parks: ParksBlock, estimate: EstimateBlock, visa: VisaBlock, trip_budget: TripBudgetBlock };

export default function Blocks({ blocks, t, lang, onAsk }) {
  if (!blocks?.length) return null;
  return (
    <div className="blocks">
      {blocks.map((block, index) => {
        const Renderer = RENDERERS[block.type];
        return Renderer ? <Renderer key={`${block.type}-${index}`} block={block} t={t} lang={lang} onAsk={onAsk} /> : null;
      })}
    </div>
  );
}
