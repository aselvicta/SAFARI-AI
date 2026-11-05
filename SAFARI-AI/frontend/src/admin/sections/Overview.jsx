import { useState } from "react";
import { fetchOverview, runHarvest } from "../api";
import { BarList, TimeSeries, useLoad } from "../charts";
import { ago, compact, label, ms, number, percent } from "../format";
import { Card, ErrorNote, Status, StatTile, sourceTone } from "../ui";

export const SERIES = {
  questions: { key: "questions", label: "Questions", color: "var(--viz-1)", area: true },
  abstained: { key: "abstained", label: "Declined", color: "var(--viz-2)" },
};

const ALERT_TONE = { critical: "critical", warning: "warning", info: "info" };
const ACTION_LABEL = { harvest: "Sync now", documents: "Documents", parks: "Parks", insights: "Insights", questions: "Questions", feedback: "Review", system: "System", sources: "Sources" };

export default function Overview({ days, go }) {
  const { data, error, loading, reload } = useLoad(() => fetchOverview(days), [days]);
  const [syncing, setSyncing] = useState("");

  async function sync() {
    setSyncing("Syncing TANAPA data…");
    try {
      const result = await runHarvest(false);
      setSyncing(result.message);
      reload();
    } catch (failure) {
      setSyncing(failure.message);
    }
  }

  if (!data) return <ErrorNote error={error} />;
  const now = data.kpis.current;
  const before = data.kpis.previous;
  const totals = data.inventory_totals;

  return (
    <div className={`dash-stack ${loading ? "refreshing" : ""}`}>
      <ErrorNote error={error} />
      {data.alerts.length ? (
        <Card title="Needs attention" subtitle={`${data.alerts.length} item${data.alerts.length === 1 ? "" : "s"}`}>
          <ul className="alert-list">
            {data.alerts.map((alert) => (
              <li key={alert.title} className={`alert alert-${alert.level}`}>
                <Status tone={ALERT_TONE[alert.level]}>{label(alert.level)}</Status>
                <div>
                  <strong>{alert.title}</strong>
                  <p>{alert.detail}</p>
                </div>
                {alert.action === "harvest" ? (
                  <button type="button" className="dash-button" onClick={sync} disabled={Boolean(syncing) && syncing.endsWith("…")}>
                    {ACTION_LABEL.harvest}
                  </button>
                ) : alert.action ? (
                  <button type="button" className="dash-button" onClick={() => go(alert.action)}>
                    {ACTION_LABEL[alert.action] || "Open"}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          {syncing ? <p className="dash-notice" role="status">{syncing}</p> : null}
        </Card>
      ) : null}

      <div className="hero-row">
        <div className="hero-figure">
          <span className="stat-label">Visitor questions</span>
          <span className="hero-value">{number(now.questions)}</span>
          <span className="stat-hint">
            {number(now.sessions)} visitor sessions · {now.questions_per_session ? number(now.questions_per_session, 1) : "—"} per session
          </span>
        </div>
        <div className="stat-grid">
          <StatTile label="Sessions" value={number(now.sessions)} current={now.sessions} previous={before.sessions} />
          <StatTile label="Answer rate" value={percent(now.answer_rate)} current={now.answer_rate} previous={before.answer_rate} kind="share" />
          <StatTile label="Visitor satisfaction" value={percent(now.satisfaction)} hint={`${number(now.feedback)} rating${now.feedback === 1 ? "" : "s"}`} />
          <StatTile label="Median response" value={ms(now.median_latency_ms)} current={now.median_latency_ms} previous={before.median_latency_ms} goodWhen="down" />
          <StatTile label="Answered by LLM agent" value={percent(now.agent_share)} hint={data.llm_enabled ? "rest by the composer" : "agent is off"} />
          <StatTile label="Answers with citations" value={percent(now.cited_share)} current={now.cited_share} previous={before.cited_share} kind="share" />
        </div>
      </div>

      <Card title="Questions per day" subtitle="East Africa Time. Declined means the official sources did not cover the question.">
        <TimeSeries rows={data.series} series={[SERIES.questions, SERIES.abstained]} label="Questions and declined answers per day" />
      </Card>

      <div className="dash-grid two">
        <Card title="Most asked-about parks" actions={<button type="button" className="dash-link" onClick={() => go("insights")}>All insights →</button>}>
          <BarList items={data.parks} limit={8} empty="No park has been asked about in this period." onSelect={(item) => go("questions", { park: item.key })} />
        </Card>
        <Card title="What visitors ask about">
          <BarList items={data.intents.map((item) => ({ ...item, label: label(item.key) }))} limit={8} onSelect={(item) => go("questions", { intent: item.key })} />
        </Card>
      </div>

      <div className="dash-grid two">
        <Card title="Data from tanzaniaparks.go.tz" actions={<button type="button" className="dash-link" onClick={() => go("parks")}>Parks →</button>}>
          <dl className="kv-grid">
            <div><dt>Parks</dt><dd>{number(totals.parks)}</dd></div>
            <div><dt>Fee rows in force</dt><dd>{compact(totals.tariff_rows_in_force)}</dd></div>
            <div><dt>All fee rows</dt><dd>{compact(totals.tariff_rows)}</dd></div>
            <div><dt>Activities</dt><dd>{number(totals.activities)}</dd></div>
            <div><dt>Accommodation types</dt><dd>{number(totals.accommodation)}</dd></div>
            <div><dt>Documents indexed</dt><dd>{number(totals.documents)}</dd></div>
            <div><dt>Search chunks</dt><dd>{compact(totals.chunks)}</dd></div>
            <div><dt>Scanned PDFs (no text)</dt><dd>{number(totals.needs_ocr)}</dd></div>
          </dl>
        </Card>
        <Card title="Source health" actions={<button type="button" className="dash-link" onClick={() => go("sources")}>Sources →</button>}>
          <ul className="source-mini">
            {data.sources.map((source) => (
              <li key={source.id}>
                <Status tone={sourceTone(source.status)}>{source.status || "unknown"}</Status>
                <span className="source-name">{source.name || source.id}</span>
                <span className="source-age">{ago(source.last_success)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
