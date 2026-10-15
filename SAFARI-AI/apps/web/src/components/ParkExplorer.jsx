import { useMemo, useState } from "react";
import ParkCard, { zoneLabel } from "./ParkCard";
import { format } from "../i18n";

export default function ParkExplorer({ t, parks, onAsk }) {
  const [zone, setZone] = useState("");
  const [query, setQuery] = useState("");

  const zones = useMemo(() => [...new Set(parks.map(zoneLabel).filter(Boolean))].sort(), [parks]);
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return parks.filter((park) => {
      if (zone && zoneLabel(park) !== zone) return false;
      if (!needle) return true;
      return `${park.name} ${park.slogan || ""} ${(park.activities || []).join(" ")}`.toLowerCase().includes(needle);
    });
  }, [parks, zone, query]);

  return (
    <section className="explorer" id="parks" aria-labelledby="explorer-title">
      <header className="explorer-head">
        <h2 id="explorer-title" className="display big">
          {t.explorerTitle}
        </h2>
        <p>{t.explorerSub}</p>
      </header>
      {parks.length ? (
        <>
          <div className="explorer-tools">
            <div className="filter-chips" role="group" aria-label="Zone">
              <button type="button" className="chip on-dark" aria-pressed={!zone} onClick={() => setZone("")}>
                {t.all}
              </button>
              {zones.map((item) => (
                <button key={item} type="button" className="chip on-dark" aria-pressed={zone === item} onClick={() => setZone(item)}>
                  {item}
                </button>
              ))}
            </div>
            <label className="search" htmlFor="park-search">
              <span className="sr">{t.searchParks}</span>
              <input
                id="park-search"
                type="search"
                placeholder={t.searchParks}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
          </div>
          {visible.length ? (
            <div className="park-grid">
              {visible.map((park) => (
                <ParkCard key={park.slug} park={park} t={t} onPlan={(chosen) => onAsk(format(t.askAbout, { name: chosen.name }))} />
              ))}
            </div>
          ) : (
            <p className="empty-note">{t.noParkMatch}</p>
          )}
        </>
      ) : (
        <p className="empty-note">{t.emptyParks}</p>
      )}
    </section>
  );
}
