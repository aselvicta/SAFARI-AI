// Small SVG/CSS charts for the dashboard: a time series with crosshair, ranked bars, hourly columns.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { compact, formatDay } from "./format";

function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(600);
  useLayoutEffect(() => {
    if (!ref.current) return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function niceMax(value) {
  if (value <= 4) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (step * magnitude >= value) return step * magnitude;
  }
  return 10 * magnitude;
}

/** Daily series on one shared axis. `series`: [{ key, label, color }], `rows`: [{ date, [key]: n }]. */
export function TimeSeries({ rows, series, height = 220, label }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const [showTable, setShowTable] = useState(false);
  const pad = { top: 16, right: 56, bottom: 26, left: 36 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(1, ...rows.flatMap((row) => series.map((item) => row[item.key] || 0))));
  const x = (index) => pad.left + (rows.length <= 1 ? plotW / 2 : (index / (rows.length - 1)) * plotW);
  const y = (value) => pad.top + plotH - (value / max) * plotH;
  const ticks = [0, max / 2, max];
  const labelEvery = Math.max(1, Math.ceil(rows.length / Math.max(2, Math.floor(plotW / 80))));

  function move(event) {
    const box = event.currentTarget.getBoundingClientRect();
    const position = ((event.clientX - box.left - pad.left) / plotW) * (rows.length - 1);
    setHover(Math.min(rows.length - 1, Math.max(0, Math.round(position))));
  }

  function key(event) {
    if (event.key === "ArrowRight") setHover((value) => Math.min(rows.length - 1, (value ?? -1) + 1));
    else if (event.key === "ArrowLeft") setHover((value) => Math.max(0, (value ?? rows.length) - 1));
  }

  const active = hover === null ? null : rows[hover];
  const last = rows.length - 1;

  return (
    <div className="viz" ref={ref}>
      {series.length > 1 ? (
        <ul className="viz-legend">
          {series.map((item) => (
            <li key={item.key}>
              <span className="viz-key-line" style={{ background: item.color }} />
              {item.label}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="viz-frame">
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={label}
          tabIndex={0}
          onPointerMove={move}
          onPointerLeave={() => setHover(null)}
          onFocus={() => setHover(last)}
          onBlur={() => setHover(null)}
          onKeyDown={key}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={pad.left} x2={pad.left + plotW} y1={y(tick)} y2={y(tick)} className={tick === 0 ? "viz-base" : "viz-grid"} />
              <text x={pad.left - 8} y={y(tick)} dy="0.32em" textAnchor="end" className="viz-tick">
                {compact(tick)}
              </text>
            </g>
          ))}
          {rows.map((row, index) =>
            index % labelEvery === 0 || index === last ? (
              <text key={row.date} x={x(index)} y={height - 6} textAnchor="middle" className="viz-tick">
                {formatDay(row.date)}
              </text>
            ) : null,
          )}
          {series.map((item) => {
            const points = rows.map((row, index) => `${x(index)},${y(row[item.key] || 0)}`).join(" ");
            const area = `${pad.left},${y(0)} ${points} ${x(last)},${y(0)}`;
            return (
              <g key={item.key}>
                {item.area ? <polygon points={area} fill={item.color} opacity="0.1" /> : null}
                <polyline points={points} fill="none" stroke={item.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
                {rows.length ? (
                  <>
                    <circle cx={x(last)} cy={y(rows[last][item.key] || 0)} r="4" fill={item.color} className="viz-dot" />
                    <text x={x(last) + 8} y={y(rows[last][item.key] || 0)} dy="0.32em" className="viz-end">
                      {compact(rows[last][item.key] || 0)}
                    </text>
                  </>
                ) : null}
              </g>
            );
          })}
          {active ? (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={pad.top + plotH} className="viz-cross" />
              {series.map((item) => (
                <circle key={item.key} cx={x(hover)} cy={y(active[item.key] || 0)} r="4" fill={item.color} className="viz-dot" />
              ))}
            </g>
          ) : null}
        </svg>
        {active ? (
          <div className="viz-tip" style={{ left: Math.min(width - 150, Math.max(0, x(hover) + 12)), top: pad.top }} role="status">
            <div className="viz-tip-head">{formatDay(active.date, true)}</div>
            {series.map((item) => (
              <div key={item.key} className="viz-tip-row">
                <span className="viz-key-line" style={{ background: item.color }} />
                <strong>{(active[item.key] || 0).toLocaleString()}</strong>
                <span>{item.label}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <button type="button" className="viz-table-toggle" onClick={() => setShowTable((value) => !value)} aria-expanded={showTable}>
        {showTable ? "Hide table" : "Show table"}
      </button>
      {showTable ? (
        <div className="table-wrap viz-table">
          <table>
            <thead>
              <tr>
                <th scope="col">Date</th>
                {series.map((item) => (
                  <th key={item.key} scope="col" className="num">
                    {item.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.date}>
                  <td>{formatDay(row.date, true)}</td>
                  {series.map((item) => (
                    <td key={item.key} className="num">
                      {(row[item.key] || 0).toLocaleString()}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

/** Ranked horizontal bars, one series. `items`: [{ key, label?, count }]. */
export function BarList({ items, empty = "No data yet.", format = (value) => value.toLocaleString(), limit = 10, onSelect }) {
  const [hover, setHover] = useState(null);
  const shown = items.slice(0, limit);
  if (!shown.length) return <p className="viz-empty">{empty}</p>;
  const max = Math.max(...shown.map((item) => item.count), 1);
  const total = items.reduce((sum, item) => sum + item.count, 0);
  return (
    <ul className="bar-list">
      {shown.map((item) => {
        const share = total ? item.count / total : 0;
        const content = (
          <>
            <span className="bar-label">{item.label || item.key}</span>
            <span className="bar-track">
              <span className="bar-fill" style={{ width: `${Math.max(2, (item.count / max) * 100)}%` }} />
            </span>
            <span className="bar-value">{format(item.count)}</span>
            {hover === item.key ? (
              <span className="viz-tip bar-tip" role="status">
                <strong>{format(item.count)}</strong> <span>{`${Math.round(share * 100)}% of total`}</span>
              </span>
            ) : null}
          </>
        );
        const handlers = {
          onPointerEnter: () => setHover(item.key),
          onPointerLeave: () => setHover(null),
          onFocus: () => setHover(item.key),
          onBlur: () => setHover(null),
        };
        return (
          <li key={item.key}>
            {onSelect ? (
              <button type="button" className="bar-row" onClick={() => onSelect(item)} {...handlers}>
                {content}
              </button>
            ) : (
              <div className="bar-row" tabIndex={0} {...handlers}>
                {content}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** 24 columns, one per hour of the day (East Africa Time). */
export function HourColumns({ hours, height = 140 }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const pad = { top: 18, bottom: 22, left: 4, right: 4 };
  const plotH = height - pad.top - pad.bottom;
  const band = (width - pad.left - pad.right) / 24;
  const barW = Math.min(24, band - 2);
  const max = Math.max(1, ...hours);
  const peak = hours.indexOf(Math.max(...hours));
  return (
    <div className="viz" ref={ref}>
      <div className="viz-frame">
        <svg width={width} height={height} role="img" aria-label="Questions by hour of day, East Africa Time">
          <line x1={pad.left} x2={width - pad.right} y1={pad.top + plotH} y2={pad.top + plotH} className="viz-base" />
          {hours.map((count, hour) => {
            const h = count ? Math.max(3, (count / max) * plotH) : 0;
            const x = pad.left + hour * band + (band - barW) / 2;
            const top = pad.top + plotH - h;
            const r = Math.min(4, h, barW / 2);
            const path = h
              ? `M${x},${pad.top + plotH} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${pad.top + plotH} Z`
              : "";
            return (
              <g
                key={hour}
                tabIndex={0}
                onPointerEnter={() => setHover(hour)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(hour)}
                onBlur={() => setHover(null)}
                aria-label={`${String(hour).padStart(2, "0")}:00, ${count} questions`}
              >
                <rect x={pad.left + hour * band} y={pad.top} width={band} height={plotH} fill="transparent" />
                {path ? <path d={path} className={hover === hour ? "col-fill hover" : "col-fill"} /> : null}
                {hour === peak && count ? (
                  <text x={x + barW / 2} y={top - 5} textAnchor="middle" className="viz-end">
                    {count}
                  </text>
                ) : null}
                {hour % 3 === 0 ? (
                  <text x={x + barW / 2} y={height - 6} textAnchor="middle" className="viz-tick">
                    {String(hour).padStart(2, "0")}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
        {hover !== null ? (
          <div className="viz-tip" style={{ left: Math.min(width - 140, pad.left + hover * band), top: 0 }} role="status">
            <strong>{hours[hover].toLocaleString()}</strong> <span>{`questions at ${String(hover).padStart(2, "0")}:00 EAT`}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Completeness or a share, 0–1, as a thin meter. */
export function Meter({ value, label }) {
  const percent = Math.round((value || 0) * 100);
  const tone = percent >= 100 ? "ok" : percent >= 60 ? "mid" : "low";
  return (
    <span className={`meter meter-${tone}`} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={label}>
      <span style={{ width: `${percent}%` }} />
    </span>
  );
}

/** Calls `load` now and again whenever `deps` change; keeps the previous data while reloading. */
export function useLoad(load, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((current) => ({ ...current, loading: true }));
    load()
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((error) => alive && setState((current) => ({ data: current.data, error, loading: false })));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((value) => value + 1) };
}
