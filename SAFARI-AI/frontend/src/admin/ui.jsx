// Building blocks shared by the dashboard sections.
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
export function StatTile({ label, value, current, previous, kind = "count", goodWhen = "up", hint }) {
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
    <div className="stat-tile">
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

export function Pager({ total, limit, offset, onChange }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav className="pager" aria-label="Pages">
      <button type="button" className="dash-button" disabled={page <= 1} onClick={() => onChange(offset - limit)}>
        ← Newer
      </button>
      <span>
        Page {page} of {pages}
      </span>
      <button type="button" className="dash-button" disabled={page >= pages} onClick={() => onChange(offset + limit)}>
        Older →
      </button>
    </nav>
  );
}
