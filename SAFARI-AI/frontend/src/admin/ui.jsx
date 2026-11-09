// Building blocks shared by the dashboard sections.
import { useState } from "react";
import { Sparkline } from "./charts";
import { percent } from "./format";

export function Card({ title, subtitle, actions, children, className = "", id }) {
  return (
    <section className={`dash-card ${className}`} id={id}>
      {title || actions ? (
        <header className="dash-card-head">
          <div>
            {title ? <h2>{title}</h2> : null}
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          {actions ? <div className="dash-card-actions">{actions}</div> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

/**
 * label · value · delta vs the previous period. `goodWhen` says which direction is good.
 * `kind`: "count" compares relative change, "share" compares percentage points.
 */
export function StatTile({ label, value, current, previous, kind = "count", goodWhen = "up", hint, trend, hero = false }) {
  let delta = null;
  if (typeof current === "number" && typeof previous === "number") {
    if (kind === "share") {
      const points = (current - previous) * 100;
      if (Math.abs(points) >= 0.5) delta = { text: `${points > 0 ? "+" : "−"}${Math.abs(points).toFixed(0)} pts`, up: points > 0 };
    } else if (previous > 0) {
      const change = (current - previous) / previous;
      if (Math.abs(change) >= 0.005) delta = { text: `${change > 0 ? "+" : "−"}${percent(Math.abs(change))}`, up: change > 0 };
    } else if (current > 0) {
      delta = { text: "new", up: true };
    }
  }
  const good = delta && (goodWhen === "up" ? delta.up : !delta.up);
  return (
    <div className={`stat-tile${hero ? " stat-hero" : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      <span className="stat-foot">
        {delta ? (
          <span className={`stat-delta ${good ? "good" : "bad"}`}>
            <span aria-hidden="true">{delta.up ? "▲" : "▼"}</span> {delta.text}
          </span>
        ) : null}
        <span className="stat-hint">{hint || (delta ? "vs previous period" : "")}</span>
      </span>
      {trend ? <Sparkline rows={trend.rows} field={trend.field} format={trend.format} label={`${label} per day`} /> : null}
    </div>
  );
}

const STATUS_ICON = { ok: "✓", good: "✓", error: "✕", critical: "✕", warning: "!", warn: "!", info: "i", empty: "–", open: "•" };

/** A state badge: icon + label, so colour never carries the meaning alone. */
export function Status({ tone = "neutral", children }) {
  return (
    <span className={`status status-${tone}`}>
      <span aria-hidden="true" className="status-icon">
        {STATUS_ICON[tone] || "•"}
      </span>
      {typeof children === "string" ? children.charAt(0).toUpperCase() + children.slice(1) : children}
    </span>
  );
}

export function sourceTone(status) {
  if (status === "ok") return "ok";
  if (status === "error") return "critical";
  return "warning";
}

export function Empty({ children }) {
  return <p className="dash-empty">{children}</p>;
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return (
    <p className="dash-error" role="alert">
      {error.message || String(error)}
    </p>
  );
}

export function Select({ label, value, onChange, options, className = "" }) {
  return (
    <label className={`dash-field ${className}`}>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => {
          const [optionValue, optionLabel] = Array.isArray(option) ? option : [option, option];
          return (
            <option key={optionValue} value={optionValue}>
              {optionLabel}
            </option>
          );
        })}
      </select>
    </label>
  );
}

export function Search({ label = "Search", value, onChange, placeholder }) {
  return (
    <label className="dash-field dash-search">
      <span>{label}</span>
      <input type="search" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

export function Pager({ total, limit, offset, onChange, newer = "← Previous", older = "Next →" }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav className="pager" aria-label="Pages">
      <span className="pager-range">
        {(offset + 1).toLocaleString()}–{Math.min(total, offset + limit).toLocaleString()} of {total.toLocaleString()}
      </span>
      <button type="button" className="dash-button" disabled={page <= 1} onClick={() => onChange(Math.max(0, offset - limit))}>
        {newer}
      </button>
      <span className="pager-page">
        Page {page} of {pages}
      </span>
      <button type="button" className="dash-button" disabled={page >= pages} onClick={() => onChange(offset + limit)}>
        {older}
      </button>
    </nav>
  );
}

/** Placeholder blocks shown only on the first load of a section, never on a refetch. */
export function Skeleton({ layout = "overview" }) {
  const blocks = {
    overview: ["kpis", "chart-wide", "chart-side", "third", "third", "third"],
    insights: ["tabs", "chart-wide", "chart-side", "half", "half"],
    table: ["filters", "table"],
    cards: ["third", "third", "third", "table"],
  }[layout] || ["table"];
  return (
    <div className="skeleton-grid" aria-busy="true" aria-label="Loading">
      {blocks.map((block, index) => (
        <div key={index} className={`skeleton skeleton-${block}`} />
      ))}
    </div>
  );
}

/** Tabs within a section. `value` is the active id; `tabs`: [[id, label]]. */
export function Tabs({ tabs, value, onChange, label }) {
  return (
    <div className="dash-tabs" role="tablist" aria-label={label}>
      {tabs.map(([id, text]) => (
        <button key={id} type="button" role="tab" aria-selected={value === id} className={value === id ? "active" : ""} onClick={() => onChange(id)}>
          {text}
        </button>
      ))}
    </div>
  );
}

/** A compact single-choice control, e.g. the period presets. `options`: [[value, label, longLabel?]]. */
export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map(([optionValue, text, long]) => (
        <button
          key={optionValue}
          type="button"
          role="radio"
          aria-checked={value === optionValue}
          title={long}
          className={value === optionValue ? "active" : ""}
          onClick={() => onChange(optionValue)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

const ALERT_ICON = { critical: "✕", warning: "!", info: "i" };

/**
 * Alerts as a compact strip: problems (critical, warning) always show; notices (info) fold behind a
 * toggle so the numbers stay above the fold.
 */
export function AlertStrip({ alerts, renderAction }) {
  const [open, setOpen] = useState(false);
  if (!alerts.length) {
    return (
      <div className="alert-strip all-clear" role="status">
        <span className="status status-ok">
          <span aria-hidden="true" className="status-icon">✓</span>All clear
        </span>
        <span>Sources are syncing and the desk is answering normally.</span>
      </div>
    );
  }
  const problems = alerts.filter((alert) => alert.level !== "info");
  const notices = alerts.filter((alert) => alert.level === "info");
  const shown = open ? alerts : problems.length ? problems : [];
  return (
    <section className="alert-strip" aria-label="Needs attention">
      <header className="alert-strip-head">
        <h2>Needs attention</h2>
        <span className="alert-counts">
          {problems.length ? `${problems.length} problem${problems.length === 1 ? "" : "s"}` : "No problems"}
          {notices.length ? ` · ${notices.length} notice${notices.length === 1 ? "" : "s"}` : ""}
        </span>
        {notices.length ? (
          <button type="button" className="dash-link" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
            {open ? "Show problems only" : problems.length ? `Show all ${alerts.length}` : `Show ${notices.length} notice${notices.length === 1 ? "" : "s"}`}
          </button>
        ) : null}
      </header>
      {shown.length ? (
        <ul className="alert-rows">
          {shown.map((alert) => (
            <li key={alert.title} className={`alert-row alert-${alert.level}`}>
              <span className={`alert-icon tone-${alert.level}`} aria-hidden="true">
                {ALERT_ICON[alert.level]}
              </span>
              <span className="visually-hidden">{alert.level}: </span>
              <strong>{alert.title}</strong>
              <span className="alert-detail" title={alert.detail}>
                {alert.detail}
              </span>
              {renderAction(alert)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
