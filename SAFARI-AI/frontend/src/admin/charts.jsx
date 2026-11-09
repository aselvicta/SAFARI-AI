// Small SVG/CSS charts for the dashboard: a time series with crosshair, ranked bars, hourly columns.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { EMPTY, compact, formatDay } from "./format";

function useWidth(floor = 240, initial = 600) {
  const ref = useRef(null);
  const [width, setWidth] = useState(initial);
  useLayoutEffect(() => {
    if (!ref.current) return undefined;
    setWidth(Math.max(floor, ref.current.getBoundingClientRect().width));
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(floor, entry.contentRect.width)));
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

/**
 * Daily series on one shared axis. `series`: [{ key, label, color, area? }], `rows`: [{ date, partial?, [key]: n }].
 * Rows marked `partial` (today so far, or a window that starts mid-day) are drawn faded so a half-finished
 * day doesn't read as a drop. `format` renders values (counts by default).
 */
export function TimeSeries({ rows, series, height = 220, label, format = (value) => value.toLocaleString(), axisFormat = compact }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const [showTable, setShowTable] = useState(false);
  const pad = { top: 16, right: 56, bottom: 26, left: 36 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(1, ...rows.flatMap((row) => series.map((item) => row[item.key] || 0))));
  const hasPartial = rows.some((row) => row.partial);
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
      {series.length > 1 || hasPartial ? (
        <ul className="viz-legend">
          {series.length > 1
            ? series.map((item) => (
                <li key={item.key}>
                  <span className="viz-key-line" style={{ background: item.color }} />
                  {item.label}
                </li>
              ))
            : null}
          {hasPartial ? (
            <li className="viz-legend-note">
              <span className="viz-key-line partial" />
              Partial day
            </li>
          ) : null}
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
                {axisFormat(tick)}
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
            // Missing values (a day with no data) are gaps, not zeros. Pairs touching a partial day are faded.
            const has = (index) => rows[index][item.key] != null;
            let solid = "";
            let faded = "";
            const runs = [];
            let run = [];
            rows.forEach((row, index) => {
              if (has(index)) run.push(index);
              else if (run.length) runs.push(run), (run = []);
              if (index === 0 || !has(index) || !has(index - 1)) return;
              const pair = `M${x(index - 1)},${y(rows[index - 1][item.key])}L${x(index)},${y(row[item.key])}`;
              if (row.partial || rows[index - 1].partial) faded += pair;
              else solid += pair;
            });
            if (run.length) runs.push(run);
            const area = runs
              .filter((indices) => indices.length > 1)
              .map((indices) => `M${x(indices[0])},${y(0)}${indices.map((index) => `L${x(index)},${y(rows[index][item.key])}`).join("")}L${x(indices[indices.length - 1])},${y(0)}Z`)
              .join("");
            const end = [...rows.keys()].reverse().find(has);
            const endPartial = end !== undefined && rows.length > 1 && rows[end].partial;
            const lineProps = { fill: "none", stroke: item.color, strokeWidth: 2, strokeLinejoin: "round", strokeLinecap: "round" };
            return (
              <g key={item.key}>
                {item.area && area ? <path d={area} fill={item.color} opacity="0.1" /> : null}
                {solid ? <path d={solid} {...lineProps} /> : null}
                {faded ? <path d={faded} {...lineProps} className="viz-partial" /> : null}
                {end !== undefined ? (
                  <>
                    <circle
                      cx={x(end)}
                      cy={y(rows[end][item.key])}
                      r="4"
                      fill={endPartial ? "var(--dash-surface)" : item.color}
                      stroke={item.color}
                      strokeWidth={endPartial ? 2 : 0}
                      className="viz-dot"
                    />
                    <text x={x(end) + 8} y={y(rows[end][item.key])} dy="0.32em" className="viz-end">
                      {axisFormat(rows[end][item.key])}
                    </text>
                  </>
                ) : null}
              </g>
            );
          })}
          {active ? (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={pad.top + plotH} className="viz-cross" />
              {series.map((item) =>
                active[item.key] == null ? null : <circle key={item.key} cx={x(hover)} cy={y(active[item.key])} r="4" fill={item.color} className="viz-dot" />,
              )}
            </g>
          ) : null}
        </svg>
        {active ? (
          <div className="viz-tip" style={{ left: Math.min(width - 150, Math.max(0, x(hover) + 12)), top: pad.top }} role="status">
            <div className="viz-tip-head">
              {formatDay(active.date, true)}
              {active.partial ? <span className="viz-tip-note">{hover === last ? "so far" : "part of day"}</span> : null}
            </div>
            {series.map((item) => (
              <div key={item.key} className="viz-tip-row">
                <span className="viz-key-line" style={{ background: item.color }} />
                <strong>{active[item.key] == null ? EMPTY : format(active[item.key])}</strong>
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
                  <td>
                    {formatDay(row.date, true)}
                    {row.partial ? <span className="cell-sub">partial day</span> : null}
                  </td>
                  {series.map((item) => (
                    <td key={item.key} className="num">
                      {row[item.key] == null ? EMPTY : format(row[item.key])}
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

/** Completeness or a share, 0 to 1, as a thin meter. */
export function Meter({ value, label }) {
  const percent = Math.round((value || 0) * 100);
  const tone = percent >= 100 ? "ok" : percent >= 60 ? "mid" : "low";
  return (
    <span className={`meter meter-${tone}`} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={label}>
      <span style={{ width: `${percent}%` }} />
    </span>
  );
}


/** A 12+ point trend for a stat tile: the de-emphasis line, the latest point in the accent. */
export function Sparkline({ rows, field, format = (value) => value.toLocaleString(), label }) {
  const [ref, width] = useWidth(40, 120);
  const [hover, setHover] = useState(null);
  const points = rows.filter((row) => !row.partial && row[field] != null);
  if (points.length < 2) return <div className="spark spark-empty" ref={ref} />;
  const height = 36;
  const pad = 4;
  const values = points.map((row) => row[field]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (index) => pad + (index / (points.length - 1)) * (width - pad * 2);
  const y = (value) => pad + (1 - (value - min) / span) * (height - pad * 2);
  const line = points.map((row, index) => `${x(index)},${y(row[field])}`).join(" ");
  const lastIndex = points.length - 1;
  const active = hover === null ? null : points[hover];
  return (
    <div className="spark" ref={ref}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`${label}: ${format(values[0])} on ${formatDay(points[0].date)} to ${format(values[lastIndex])} on ${formatDay(points[lastIndex].date)}`}
        onPointerMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          setHover(Math.min(lastIndex, Math.max(0, Math.round(((event.clientX - box.left - pad) / (width - pad * 2)) * lastIndex))));
        }}
        onPointerLeave={() => setHover(null)}
      >
        <polyline points={line} fill="none" className="spark-line" />
        <circle cx={x(lastIndex)} cy={y(values[lastIndex])} r="3.5" className="spark-dot" />
        {active ? <circle cx={x(hover)} cy={y(active[field])} r="3.5" className="spark-hover" /> : null}
      </svg>
      {active ? (
        <span className="viz-tip spark-tip" style={{ left: Math.min(width - 120, Math.max(0, x(hover) - 50)) }} role="status">
          <strong>{format(active[field])}</strong> <span>{formatDay(active.date)}</span>
        </span>
      ) : null}
    </div>
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
// Sequential blue, light → dark (validated as an ordinal ramp against the card surface).
const HEAT_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];

function heatColor(value, max) {
  if (!value) return "var(--dash-heat-0)";
  const index = Math.min(HEAT_RAMP.length - 1, Math.floor((value / max) * HEAT_RAMP.length));
  return HEAT_RAMP[index];
}

/** Weekday × hour grid (East Africa Time): when visitors ask. `grid`: 7 rows (Monday first) of 24 counts. */
export function Heatmap({ grid, label = "Questions by weekday and hour, East Africa Time" }) {
  const [ref, width] = useWidth();
  const [cursor, setCursor] = useState(null);
  const [showTable, setShowTable] = useState(false);
  const labelW = 38;
  const gap = 2;
  const cell = Math.max(8, (width - labelW) / 24 - gap);
  const cellH = Math.min(30, Math.max(14, cell * 0.6));
  const top = 18;
  const height = top + 7 * (cellH + gap);
  const max = Math.max(1, ...grid.flat());
  const total = grid.flat().reduce((sum, value) => sum + value, 0);
  let peak = [0, 0];
  grid.forEach((row, day) => row.forEach((value, hour) => (value > grid[peak[0]][peak[1]] ? (peak = [day, hour]) : null)));
  const at = (day, hour) => ({ x: labelW + hour * (cell + gap), y: top + day * (cellH + gap) });
  const hourText = (hour) => `${String(hour).padStart(2, "0")}:00`;

  function key(event) {
    const [day, hour] = cursor || peak;
    const moves = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] };
    if (!moves[event.key]) return;
    event.preventDefault();
    setCursor([Math.min(6, Math.max(0, day + moves[event.key][0])), Math.min(23, Math.max(0, hour + moves[event.key][1]))]);
  }

  const active = cursor ? { day: cursor[0], hour: cursor[1], value: grid[cursor[0]][cursor[1]], ...at(cursor[0], cursor[1]) } : null;
  return (
    <div className="viz" ref={ref}>
      <div className="viz-frame">
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`${label}. Busiest: ${WEEKDAYS[peak[0]]} ${hourText(peak[1])}, ${grid[peak[0]][peak[1]]} questions.`}
          tabIndex={0}
          onKeyDown={key}
          onFocus={() => setCursor((value) => value || peak)}
          onBlur={() => setCursor(null)}
          onPointerLeave={() => setCursor(null)}
        >
          {[0, 3, 6, 9, 12, 15, 18, 21].map((hour) => (
            <text key={hour} x={at(0, hour).x} y={12} className="viz-tick">
              {String(hour).padStart(2, "0")}
            </text>
          ))}
          {grid.map((row, day) => (
            <g key={day}>
              <text x={0} y={at(day, 0).y + cellH / 2} dy="0.32em" className="viz-tick">
                {WEEKDAYS[day]}
              </text>
              {row.map((value, hour) => {
                const { x, y } = at(day, hour);
                return (
                  <rect
                    key={hour}
                    x={x}
                    y={y}
                    width={cell}
                    height={cellH}
                    rx="3"
                    fill={heatColor(value, max)}
                    className={active && active.day === day && active.hour === hour ? "heat-cell active" : "heat-cell"}
                    onPointerEnter={() => setCursor([day, hour])}
                  />
                );
              })}
            </g>
          ))}
        </svg>
        {active ? (
          <div className="viz-tip" style={{ left: Math.min(width - 170, Math.max(0, active.x - 60)), top: active.y + cellH + 6 }} role="status">
            <div className="viz-tip-head">
              {WEEKDAYS[active.day]} {hourText(active.hour)} to {hourText((active.hour + 1) % 24)}
            </div>
            <strong>{active.value.toLocaleString()}</strong> <span>questions{total ? ` · ${Math.round((active.value / total) * 100)}%` : ""}</span>
          </div>
        ) : null}
      </div>
      <div className="heat-foot">
        <span className="heat-scale" aria-hidden="true">
          <span>Fewer</span>
          {HEAT_RAMP.map((color) => (
            <i key={color} style={{ background: color }} />
          ))}
          <span>More ({max.toLocaleString()} max)</span>
        </span>
        <button type="button" className="viz-table-toggle" onClick={() => setShowTable((value) => !value)} aria-expanded={showTable}>
          {showTable ? "Hide table" : "Show table"}
        </button>
      </div>
      {showTable ? (
        <div className="table-wrap viz-table">
          <table>
            <thead>
              <tr>
                <th scope="col">Day</th>
                {grid[0].map((_, hour) => (
                  <th key={hour} scope="col" className="num">
                    {String(hour).padStart(2, "0")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.map((row, day) => (
                <tr key={day}>
                  <th scope="row">{WEEKDAYS[day]}</th>
                  {row.map((value, hour) => (
                    <td key={hour} className="num">
                      {value}
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

/**
 * One whole split into parts. `thin` (8px, no text) sits above a list that gives each part's figures;
 * `tall` (28px) prints each share inside its block where it fits and names the parts in a legend.
 * `parts`: [{ key, label, count, color }].
 */
export function SegmentedBar({ parts, variant = "thin", label }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const total = parts.reduce((sum, part) => sum + part.count, 0);
  if (!total) return <p className="viz-empty">No data in this period.</p>;
  const shown = parts.filter((part) => part.count > 0);
  const gaps = (shown.length - 1) * 2;
  const share = (part) => part.count / total;
  const text = (part) => `${Math.round(share(part) * 100)}%`;
  return (
    <div className={`segbar segbar-${variant}`} ref={ref}>
      <div className="segbar-track" role="img" aria-label={`${label}: ${shown.map((part) => `${part.label} ${part.count} (${text(part)})`).join(", ")}`}>
        {shown.map((part) => {
          const blockW = share(part) * (width - gaps);
          const fits = variant === "tall" && blockW >= text(part).length * 7.5 + 14;
          return (
            <span
              key={part.key}
              className="segbar-block"
              style={{ flexGrow: part.count, background: part.color, color: part.ink || "#fff" }}
              tabIndex={0}
              onPointerEnter={() => setHover(part.key)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(part.key)}
              onBlur={() => setHover(null)}
              aria-label={`${part.label}: ${part.count.toLocaleString()} (${text(part)})`}
            >
              {fits ? text(part) : null}
            </span>
          );
        })}
      </div>
      {hover ? (
        <span className="viz-tip segbar-tip" role="status">
          {(() => {
            const part = shown.find((item) => item.key === hover);
            return part ? (
              <>
                <strong>{part.count.toLocaleString()}</strong> <span>{`${part.label} · ${text(part)}`}</span>
              </>
            ) : null;
          })()}
        </span>
      ) : null}
      {variant === "tall" ? (
        <ul className="viz-legend segbar-legend">
          {shown.map((part) => (
            <li key={part.key}>
              <span className="viz-key-box" style={{ background: part.color }} />
              {part.label}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Two series per row on one baseline, e.g. parks asked about vs parks recommended. */
export function PairedBars({ rows, series, limit = 12, empty = "No data yet." }) {
  const [hover, setHover] = useState(null);
  const shown = rows.slice(0, limit);
  if (!shown.length) return <p className="viz-empty">{empty}</p>;
  const max = Math.max(1, ...shown.flatMap((row) => series.map((item) => row[item.key] || 0)));
  return (
    <div className="paired">
      <ul className="viz-legend">
        {series.map((item) => (
          <li key={item.key}>
            <span className="viz-key-box" style={{ background: item.color }} />
            {item.label}
          </li>
        ))}
      </ul>
      <ul className="paired-list">
        {shown.map((row) => (
          <li
            key={row.key}
            className="paired-row"
            tabIndex={0}
            onPointerEnter={() => setHover(row.key)}
            onPointerLeave={() => setHover(null)}
            onFocus={() => setHover(row.key)}
            onBlur={() => setHover(null)}
            aria-label={`${row.label}: ${series.map((item) => `${item.label} ${row[item.key] || 0}`).join(", ")}`}
          >
            <span className="bar-label">{row.label}</span>
            <span className="paired-bars">
              {series.map((item) => (
                <span key={item.key} className="paired-bar">
                  <span className="paired-fill" style={{ width: `${row[item.key] ? Math.max(1.5, (row[item.key] / max) * 100) : 0}%`, background: item.color }} />
                  <span className="paired-value">{(row[item.key] || 0).toLocaleString()}</span>
                </span>
              ))}
            </span>
            {hover === row.key ? (
              <span className="viz-tip bar-tip" role="status">
                {series.map((item) => (
                  <span key={item.key} className="viz-tip-row">
                    <span className="viz-key-box" style={{ background: item.color }} />
                    <strong>{(row[item.key] || 0).toLocaleString()}</strong>
                    <span>{item.label}</span>
                  </span>
                ))}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A share (0 to 1) against its whole: accent fill on a lighter step of the same hue. */
export function ShareMeter({ value, label, hint }) {
  const percent = value == null ? null : Math.round(value * 100);
  return (
    <div className="share-meter">
      <div className="share-meter-head">
        <span className="share-meter-label">{label}</span>
        <strong>{percent == null ? EMPTY : `${percent}%`}</strong>
      </div>
      <span className="share-meter-track" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? 0} aria-label={label}>
        <span style={{ width: `${percent ?? 0}%` }} />
      </span>
      {hint ? <span className="share-meter-hint">{hint}</span> : null}
    </div>
  );
}

export { useLoad, useQuery } from "./data";
