import { useState } from "react";
import { format } from "../i18n";

const EAC = ["kenya", "uganda", "rwanda", "burundi", "south sudan", "dr congo", "drc", "democratic republic of the congo", "congo", "somalia"];
const TANZANIA = ["tanzania", "tz", "tanzanian", "zanzibar"];

export function visitorClass(passport) {
  const value = (passport || "").trim().toLowerCase();
  if (!value) return null;
  if (TANZANIA.includes(value)) return "resident";
  if (EAC.includes(value)) return "eac";
  return "non_resident";
}

export const EMPTY_TRIP = { passport: "", origin: "", date: "", days: "", adults: "", childAges: [] };

function NumberField({ id, label, value, onChange, min = 0, max = 99 }) {
  return (
    <label className="field" htmlFor={id}>
      <span>{label}</span>
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export default function TripPanel({ t, trip, onChange, onDownload, downloading, downloadError, open, onClose }) {
  const [age, setAge] = useState("");
  const hint = visitorClass(trip.passport);
  const set = (key) => (value) => onChange({ ...trip, [key]: value });

  function addAge(event) {
    event.preventDefault();
    const value = Number(age);
    if (age === "" || !Number.isInteger(value) || value < 0 || value > 17) return;
    onChange({ ...trip, childAges: [...trip.childAges, value] });
    setAge("");
  }

  function removeAge(index) {
    onChange({ ...trip, childAges: trip.childAges.filter((_, position) => position !== index) });
  }

  return (
    <aside className={`trip${open ? " is-open" : ""}`} aria-labelledby="trip-title">
      <header className="trip-head">
        <div>
          <h2 id="trip-title" className="display">
            {t.tripTitle}
          </h2>
          <p>{t.tripNote}</p>
        </div>
        <button type="button" className="icon-button trip-close" onClick={onClose} aria-label={t.close}>
          ✕
        </button>
      </header>
      <div className="trip-fields">
        <label className="field" htmlFor="trip-passport">
          <span>{t.passport}</span>
          <input
            id="trip-passport"
            autoComplete="country-name"
            placeholder="e.g. Germany"
            value={trip.passport}
            onChange={(event) => set("passport")(event.target.value)}
          />
        </label>
        {hint ? <p className="trip-hint">{t.visitorHint[hint]}</p> : null}
        <label className="field" htmlFor="trip-origin">
          <span>{t.origin}</span>
          <input
            id="trip-origin"
            placeholder="e.g. Arusha"
            value={trip.origin}
            onChange={(event) => set("origin")(event.target.value)}
          />
        </label>
        <label className="field" htmlFor="trip-date">
          <span>{t.travelDate}</span>
          <input id="trip-date" type="date" value={trip.date} onChange={(event) => set("date")(event.target.value)} />
        </label>
        <div className="field-row">
          <NumberField id="trip-days" label={t.days} value={trip.days} onChange={set("days")} min={1} max={60} />
          <NumberField id="trip-adults" label={t.adults} value={trip.adults} onChange={set("adults")} />
        </div>
        <div className="field">
          <label htmlFor="trip-age">
            <span>{t.childAges}</span>
          </label>
          <div className="age-entry">
            <input
              id="trip-age"
              type="number"
              inputMode="numeric"
              min={0}
              max={17}
              placeholder="Age, e.g. 7"
              value={age}
              onChange={(event) => setAge(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") addAge(event);
              }}
            />
            <button type="button" className="secondary-button" onClick={addAge}>
              {t.addAge}
            </button>
          </div>
          {trip.childAges.length ? (
            <ul className="age-chips">
              {trip.childAges.map((value, index) => (
                <li key={`${value}-${index}`}>
                  <button type="button" onClick={() => removeAge(index)} aria-label={format(t.removeAge, { age: value })}>
                    {value} <span aria-hidden="true">✕</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
      <div className="trip-actions">
        <button type="button" className="primary-button wide" onClick={onDownload} disabled={downloading}>
          {downloading ? t.downloading : t.downloadPdf}
        </button>
        <button type="button" className="ghost-button" onClick={() => onChange(EMPTY_TRIP)}>
          {t.clearTrip}
        </button>
      </div>
      {downloadError ? (
        <p className="trip-error" role="alert">
          {downloadError}
        </p>
      ) : null}
    </aside>
  );
}
