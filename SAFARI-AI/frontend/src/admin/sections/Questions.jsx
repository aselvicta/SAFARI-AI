import { Fragment, useEffect, useState } from "react";
import { downloadQuestionsCsv, queries } from "../api";
import { useQuery } from "../charts";
import { dateTime, label, ms } from "../format";
import { Card, Empty, ErrorNote, Pager, Search, Select, Skeleton, Status } from "../ui";

const LIMIT = 50;
const INTENTS = ["fee", "planning", "park_fact", "wildlife", "activity", "accommodation", "visa", "season", "rules", "safety", "contact", "scope", "unsupported", "general", "greeting", "error"];
const OUTCOMES = [
  ["", "Any outcome"],
  ["answered", "Answered"],
  ["abstained", "Declined"],
  ["low", "Low confidence"],
  ["error", "Failed"],
];

function outcome(row) {
  if (row.error) return <Status tone="critical">Failed</Status>;
  if (row.abstained) return <Status tone="warning">Declined</Status>;
  if (row.confidence_label === "LOW") return <Status tone="info">Low</Status>;
  return <Status tone="ok">Answered</Status>;
}

export default function Questions({ days, params }) {
  const [q, setQ] = useState(params.q || "");
  const [intent, setIntent] = useState(params.intent || "");
  const [park, setPark] = useState(params.park || "");
  const [result, setResult] = useState(params.outcome || "");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(null);
  const [exportError, setExportError] = useState(null);
  const [search, setSearch] = useState(q);

  const parks = useQuery(queries.parks()).data || [];
  useEffect(() => {
    setQ(params.q || "");
    setSearch(params.q || "");
    setIntent(params.intent || "");
    setPark(params.park || "");
    setResult(params.outcome || "");
  }, [params.q, params.intent, params.park, params.outcome]);
  useEffect(() => {
    const timer = setTimeout(() => setQ(search), 250);
    return () => clearTimeout(timer);
  }, [search]);
  useEffect(() => setOffset(0), [q, intent, park, result, days]);

  const { data, error, loading } = useQuery(queries.questions({ days, q, intent, park, outcome: result, limit: LIMIT, offset }));
  const names = Object.fromEntries(parks.map((item) => [item.slug, item.name.replace(/ National Park$/, "")]));

  async function exportCsv() {
    setExportError(null);
    try {
      await downloadQuestionsCsv(days);
    } catch (failure) {
      setExportError(failure);
    }
  }

  return (
    <div className="dash-stack">
      <div className="filter-row">
        <Search value={search} onChange={setSearch} placeholder="Words in the question" />
        <Select label="Intent" value={intent} onChange={setIntent} options={[["", "Any intent"], ...INTENTS.map((item) => [item, label(item)])]} />
        <Select label="Park" value={park} onChange={setPark} options={[["", "Any park"], ...parks.map((item) => [item.slug, item.name])]} />
        <Select label="Outcome" value={result} onChange={setResult} options={OUTCOMES} />
        <button type="button" className="dash-button" onClick={exportCsv}>
          Export CSV
        </button>
      </div>
      <ErrorNote error={error || exportError} />
      <Card
        title={data ? `${data.total.toLocaleString()} question${data.total === 1 ? "" : "s"}` : "Questions"}
        subtitle="Newest first. Visitors are identified only by a hashed session id; no IP addresses are stored."
        className={loading ? "refreshing" : ""}
      >
        {data && data.rows.length ? (
          <div className="table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Question</th>
                  <th scope="col">Intent</th>
                  <th scope="col">Parks</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">By</th>
                  <th scope="col" className="num">Time</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, index) => {
                  const id = `${row.at}-${index}`;
                  const expanded = open === id;
                  return (
                    <Fragment key={id}>
                      <tr className={expanded ? "row-open" : ""}>
                        <td className="nowrap">{dateTime(row.at)}</td>
                        <td>
                          <button type="button" className="dash-link left" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : id)}>
                            {row.question}
                          </button>
                        </td>
                        <td>{label(row.intent)}</td>
                        <td>{(row.parks || []).map((slug) => names[slug] || slug).join(", ") || "—"}</td>
                        <td>{outcome(row)}</td>
                        <td>{row.generator || "—"}</td>
                        <td className="num nowrap">{ms(row.latency_ms)}</td>
                      </tr>
                      {expanded ? (
                        <tr className="row-detail">
                          <td colSpan={7}>
                            <dl className="kv-grid small">
                              <div><dt>Language</dt><dd>{row.language === "sw" ? "Kiswahili" : "English"}</dd></div>
                              <div><dt>Confidence</dt><dd>{row.confidence_label || "—"} {row.confidence != null ? `(${row.confidence})` : ""}</dd></div>
                              <div><dt>Citations</dt><dd>{row.citations ?? 0}</dd></div>
                              <div><dt>Answer cards</dt><dd>{(row.blocks || []).join(", ") || "—"}</dd></div>
                              <div><dt>Tools</dt><dd>{(row.tools || []).join(", ") || "—"}</dd></div>
                              <div><dt>Recommended</dt><dd>{(row.recommended || []).map((slug) => names[slug] || slug).join(", ") || "—"}</dd></div>
                              <div><dt>Passport</dt><dd>{row.passport || "—"}</dd></div>
                              <div><dt>Fee class</dt><dd>{label(row.visitor_class)}</dd></div>
                              <div><dt>Trip</dt><dd>{[row.days && `${row.days} days`, row.adults && `${row.adults} adults`, row.children && `${row.children} children`].filter(Boolean).join(", ") || "—"}</dd></div>
                              <div><dt>Session</dt><dd><code>{row.session || "—"}</code></dd></div>
                              <div><dt>Channel</dt><dd>{row.channel}</dd></div>
                              {row.error ? <div className="wide"><dt>Error</dt><dd>{row.error}</dd></div> : null}
                            </dl>
                            <a className="dash-link" href={`/?q=${encodeURIComponent(row.question)}`} target="_blank" rel="noreferrer">
                              Ask it again on the visitor desk ↗
                            </a>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : data ? (
          <Empty>No questions match these filters.</Empty>
        ) : error ? null : (
          <Skeleton layout="table" />
        )}
        {data ? <Pager total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} newer="← Newer" older="Older →" /> : null}
      </Card>
    </div>
  );
}
