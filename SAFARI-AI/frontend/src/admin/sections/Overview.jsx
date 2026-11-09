import { useState } from "react";
import { queries, runHarvest } from "../api";
import { BarList, SegmentedBar, ShareMeter, TimeSeries, useQuery } from "../charts";
import { invalidate } from "../data";
import { ago, compact, formatDay, label, ms, number, percent } from "../format";
import { AlertStrip, Card, Empty, ErrorNote, Skeleton, Status, StatTile, sourceTone } from "../ui";

export const SERIES = {
  questions: { key: "questions", label: "Questions", color: "var(--viz-1)", area: true },
  abstained: { key: "abstained", label: "Declined", color: "var(--viz-2)" },
};

// Outcomes are states, so they wear the status colours, always beside an icon and a label.
export const OUTCOMES = {
  answered: { label: "Answered", color: "var(--good)", tone: "ok" },
  low_confidence: { label: "Low confidence", color: "var(--warning)", tone: "warning", ink: "#0b0b0b" },
  declined: { label: "Declined", color: "var(--serious)", tone: "serious" },
  failed: { label: "Failed", color: "var(--critical)", tone: "critical" },
};

const ACTION_LABEL = { harvest: "Sync now", documents: "Documents", parks: "Parks", insights: "Insights", questions: "Questions", feedback: "Review", system: "System", sources: "Sources" };

export function OutcomePanel({ outcomes }) {
  const total = outcomes.reduce((sum, item) => sum + item.count, 0);
  const parts = outcomes.map((item) => ({ key: item.key, count: item.count, ...OUTCOMES[item.key] }));
  return (
    <div className="outcomes">
      <SegmentedBar parts={parts} label="How questions ended" />
      <ul className="outcome-list">
        {parts.map((part) => (
          <li key={part.key}>
            <Status tone={part.tone}>{part.label}</Status>
            <span className="outcome-count">{number(part.count)}</span>
            <span className="outcome-share">{total ? percent(part.count / total) : "—"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function tariffState(windows) {
  const current = (windows || []).filter((window) => window.state === "in_force" && window.days_left != null);
  const soonest = current.sort((a, b) => a.days_left - b.days_left)[0];
  const upcoming = (windows || []).some((window) => window.state === "upcoming");
  if (!soonest) return null;
  return { until: soonest.valid_until, days: soonest.days_left, upcoming };
}

export default function Overview({ days, go }) {
  const { data, error, loading } = useQuery(queries.overview(days));
  const [syncing, setSyncing] = useState("");

  async function sync() {
    setSyncing("Syncing TANAPA data…");
    try {
      const result = await runHarvest(false);
      setSyncing(result.message);
      invalidate("overview", "inventory", "status");
    } catch (failure) {
      setSyncing(failure.message);
    }
  }

  if (!data) return error ? <ErrorNote error={error} /> : <Skeleton layout="overview" />;
  const now = data.kpis.current;
  const before = data.kpis.previous;
  const totals = data.inventory_totals;
  const tariff = tariffState(data.tariff_windows);
  const trend = (field, format) => ({ rows: data.series, field, format });

  return (
    <div className={`dash-stack ${loading ? "refreshing" : ""}`}>
      <ErrorNote error={error} />
      <AlertStrip
        alerts={data.alerts}
        renderAction={(alert) =>
          alert.action === "harvest" ? (
            <button type="button" className="dash-button small" onClick={sync} disabled={syncing.endsWith("…")}>
              {ACTION_LABEL.harvest}
            </button>
          ) : alert.action ? (
            <button type="button" className="dash-button small" onClick={() => go(alert.action)}>
              {ACTION_LABEL[alert.action] || "Open"}
            </button>
          ) : null
        }
      />
      {syncing ? <p className="dash-notice" role="status">{syncing}</p> : null}

      <div className="kpi-band">
        <StatTile
          hero
          label="Visitor questions"
          value={number(now.questions)}
          current={now.questions}
          previous={before.questions}
          hint={`${number(now.sessions)} sessions · ${now.questions_per_session ? number(now.questions_per_session, 1) : "—"} per session`}
          trend={trend("questions")}
        />
        <StatTile label="Sessions" value={number(now.sessions)} current={now.sessions} previous={before.sessions} trend={trend("sessions")} />
        <StatTile label="Answer rate" value={percent(now.answer_rate)} current={now.answer_rate} previous={before.answer_rate} kind="share" trend={trend("answer_rate", (value) => percent(value))} />
        <StatTile label="Median response" value={ms(now.median_latency_ms)} current={now.median_latency_ms} previous={before.median_latency_ms} goodWhen="down" trend={trend("median_latency_ms", ms)} />
        <StatTile label="Visitor satisfaction" value={percent(now.satisfaction)} hint={`${number(now.feedback)} rating${now.feedback === 1 ? "" : "s"}${now.feedback_open ? ` · ${now.feedback_open} to review` : ""}`} />
      </div>

      <div className="dash-grid main-side">
        <Card title="Questions per day" subtitle="East Africa Time. Declined: the official sources did not cover the question.">
          <TimeSeries rows={data.series} series={[SERIES.questions, SERIES.abstained]} label="Questions and declined answers per day" height={264} />
        </Card>
        <Card title="Answer quality" subtitle="How each question ended" actions={<button type="button" className="dash-link" onClick={() => go("insights", { tab: "quality" })}>Details →</button>}>
          <OutcomePanel outcomes={data.outcomes} />
          <div className="meter-stack">
            <ShareMeter label="Answers with citations" value={now.cited_share} />
            <ShareMeter label="Written by the LLM agent" value={now.agent_share} hint={data.llm_enabled ? "The rest by the template composer" : "Agent is off: set DEEPSEEK_API_KEY"} />
          </div>
        </Card>
      </div>

      <div className="dash-grid three">
        <Card title="Most asked-about parks" actions={<button type="button" className="dash-link" onClick={() => go("insights", { tab: "content" })}>All parks →</button>}>
          <BarList items={data.parks.map((item) => ({ ...item, label: item.label.replace(/ National Park$/, "") }))} limit={7} empty="No park has been asked about in this period." onSelect={(item) => go("questions", { park: item.key })} />
        </Card>
        <Card title="What visitors ask about">
          <BarList items={data.intents.map((item) => ({ ...item, label: label(item.key) }))} limit={7} onSelect={(item) => go("questions", { intent: item.key })} />
        </Card>
        <Card title="Top questions" subtitle="Asked more than once">
          {data.top_questions.length ? (
            <ol className="rank-list">
              {data.top_questions.slice(0, 7).map((item) => (
                <li key={item.question}>
                  <button type="button" className="dash-link left" onClick={() => go("questions", { q: item.question.slice(0, 60) })} title={item.question}>
                    {item.question}
                  </button>
                  <span className="rank-count">{number(item.count)}×</span>
                </li>
              ))}
            </ol>
          ) : (
            <Empty>No question has been repeated yet.</Empty>
          )}
        </Card>
      </div>

      <div className="dash-grid two">
        <Card title="Knowledge base" subtitle="Data from tanzaniaparks.go.tz and official PDFs" actions={<button type="button" className="dash-link" onClick={() => go("fees")}>Fees →</button>}>
          <dl className="kv-grid">
            <div><dt>Parks</dt><dd>{number(totals.parks)}</dd></div>
            <div><dt>Fee rows in force</dt><dd>{compact(totals.tariff_rows_in_force)}</dd></div>
            <div><dt>Documents</dt><dd>{number(totals.documents)}</dd></div>
            <div><dt>Search chunks</dt><dd>{compact(totals.chunks)}</dd></div>
            <div><dt>Activities</dt><dd>{number(totals.activities)}</dd></div>
            <div><dt>Scanned PDFs (no text)</dt><dd>{number(totals.needs_ocr)}</dd></div>
          </dl>
          {tariff ? (
            <p className="tariff-line">
              <Status tone={tariff.days > 60 || tariff.upcoming ? "ok" : "warning"}>{tariff.days > 60 || tariff.upcoming ? "Tariff current" : "Tariff ending"}</Status>
              <span>
                Valid until {formatDay(tariff.until, true)} {tariff.until.slice(0, 4)} · {number(tariff.days)} days left
                {tariff.upcoming ? " · next tariff published" : ""}
              </span>
            </p>
          ) : null}
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
