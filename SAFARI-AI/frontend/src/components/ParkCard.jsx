import { format, formatNumber } from "../i18n";

const FALLBACK_ART = ["lion", "elephant", "giraffe", "rhino", "wildebeest", "hippo"];

function fallbackArt(slug = "") {
  const total = [...slug].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return `/brand/${FALLBACK_ART[total % FALLBACK_ART.length]}.svg`;
}

export function zoneLabel(park) {
  return (park.zone || park.circuit || "").replace(/^Northen/i, "Northern").replace(/\s*zone$/i, "").trim();
}

export default function ParkCard({ park, t, onPlan, compact = false }) {
  const zone = zoneLabel(park);
  return (
    <article className={`park-card${compact ? " compact" : ""}`}>
      <div className="park-photo">
        {park.image_url ? (
          <img src={park.image_url} alt="" loading="lazy" decoding="async" />
        ) : (
          <img className="park-art" src={fallbackArt(park.slug)} alt="" />
        )}
        {zone ? <span className="park-zone">{zone}</span> : null}
      </div>
      <div className="park-body">
        <h3>{park.name}</h3>
        {park.slogan ? <p className="park-slogan">{park.slogan}</p> : null}
        {!compact && park.summary ? <p className="park-summary">{park.summary}</p> : null}
        <dl className="park-facts">
          {park.area_km2 ? (
            <div>
              <dt className="sr">Area</dt>
              <dd>{format(t.area, { n: formatNumber(park.area_km2, 2) })}</dd>
            </div>
          ) : null}
          {park.established_year ? (
            <div>
              <dt className="sr">Established</dt>
              <dd>Est. {park.established_year}</dd>
            </div>
          ) : null}
        </dl>
        {onPlan ? (
          <button type="button" className="text-button" onClick={() => onPlan(park)}>
            {t.planPark} <span aria-hidden="true">↘</span>
          </button>
        ) : null}
      </div>
    </article>
  );
}
