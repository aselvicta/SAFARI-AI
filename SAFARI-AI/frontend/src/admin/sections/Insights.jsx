import { useState } from "react";
import { queries } from "../api";
import { BarList, Heatmap, PairedBars, SegmentedBar, ShareMeter, TimeSeries, useQuery } from "../charts";
import { dateTime, label, ms, number, percent } from "../format";
import { Card, Empty, ErrorNote, Pager, Skeleton, StatTile, Tabs } from "../ui";
import { OutcomePanel } from "./Overview";

const TABS = [
  ["demand", "Demand"],
  ["audience", "Audience"],
  ["content", "Content"],
  ["quality", "Quality"],
];
// Categorical slots in fixed order (validated on the card surface); a sixth part folds into "Other".
const SLOTS = ["var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)", "var(--viz-5)", "var(--viz-muted)"];
const SLOT_INK = [null, null, null, "#0b0b0b", null, null];
const TRIP_ORDER = ["1–2 days", "3–4 days", "5–7 days", "8+ days"];
const GROUP_ORDER = ["Solo", "Couple", "3–5 people", "6+ people"];
const CONFIDENCE_ORDER = ["HIGH", "MEDIUM", "LOW"];
const LANGUAGES = { en: "English", sw: "Kiswahili", de: "German", fr: "French", es: "Spanish", it: "Italian", zh: "Chinese" };
const GAP_PAGE = 10;

/** Fixed bucket order (an ordinal scale), not ranked by count. */
function ordered(items, order) {
  const counts = Object.fromEntries(items.map((item) => [item.key, item.count]));
  return order.map((key) => ({ key, count: counts[key] || 0 }));
}

/** Up to five named parts plus "Other", each with its slot colour, for a segmented bar. */
function parts(items, name = (key) => key) {
  const top = items.slice(0, 5);
  const rest = items.slice(5).reduce((sum, item) => sum + item.count, 0);
  const shown = top.map((item, index) => ({ key: item.key, label: name(item.key), count: item.count, color: SLOTS[index], ink: SLOT_INK[index] }));
  return rest ? [...shown, { key: "other", label: "Other", count: rest, color: SLOTS[5] }] : shown;
}

function Demand({ data }) {
  const series = data.series;
  const busiest = series.filter((row) => !row.partial).sort((a, b) => b.questions - a.questions)[0];
  return (
    <>
      <div className="kpi-band four">
        <StatTile label="Sessions" value={number(data.kpis.current.sessions)} current={data.kpis.current.sessions} previous={data.kpis.previous.sessions} />
        <StatTile label="Questions per session" value={data.kpis.current.questions_per_session ? number(data.kpis.current.questions_per_session, 1) : "—"} />
        <StatTile label="Busiest day" value={busiest ? number(busiest.questions) : "—"} hint={busiest ? new Date(`${busiest.date}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) : ""} />
        <StatTile label="Daily average" value={series.length ? number(data.kpis.current.questions / Math.max(1, series.length - 1), 1) : "—"} hint="questions per day" />
      </div>
      <Card title="Visitor sessions per day" subtitle="Unique visitors, counted by hashed session">
        <TimeSeries rows={series} series={[{ key: "sessions", label: "Sessions", color: "var(--viz-1)", area: true }]} label="Visitor sessions per day" height={220} />
      </Card>
      <Card title="When visitors ask" subtitle="Questions by weekday and hour, East Africa Time. Darker is busier.">
        <Heatmap grid={data.weekday_hours} />
      </Card>
      <div className="dash-grid two">
        <Card title="Trip length" subtitle="From the trip details visitors give">
          <BarList items={ordered(data.trip_length, TRIP_ORDER)} empty="No trip lengths given yet." />
        </Card>
        <Card title="Group size">
          <BarList items={ordered(data.group_size, GROUP_ORDER)} empty="No group sizes given yet." />
        </Card>
      </div>
    </>
  );
}

function Audience({ data }) {
  return (
    <>
      <div className="dash-grid main-side">
        <Card title="Source markets" subtitle="Passport country given in trip details">
          <BarList items={data.markets} limit={12} empty="No passports given yet." />
        </Card>
        <div className="dash-stack">
          <Card title="Trip details given" subtitle="Share of questions asked with each detail filled in. More detail means exact fees and plans.">
            <div className="meter-stack tight">
              <ShareMeter label="Any trip detail" value={data.trip_details.any} />
              <ShareMeter label="Passport country" value={data.trip_details.passport} />
              <ShareMeter label="Trip length" value={data.trip_details.days} />
              <ShareMeter label="Group size" value={data.trip_details.group} />
            </div>
          </Card>
          <Card title="Fee class" subtitle="Which tariff applies to the visitor">
            <SegmentedBar variant="tall" parts={parts(data.visitor_classes, label)} label="Visitors by fee class" />
          </Card>
          <Card title="Language" subtitle="Language of the question">
            <SegmentedBar variant="tall" parts={parts(data.languages, (key) => LANGUAGES[key] || key)} label="Questions by language" />
          </Card>
        </div>
      </div>
    </>
  );
}

function Content({ data, go }) {
  const asked = Object.fromEntries(data.parks.map((item) => [item.key, item]));
  const recommended = Object.fromEntries(data.recommended.map((item) => [item.key, item]));
  const rows = [...new Set([...Object.keys(asked), ...Object.keys(recommended)])]
    .map((key) => ({
      key,
      label: (asked[key] || recommended[key]).label.replace(/ National Park$/, ""),
      asked: asked[key]?.count || 0,
      recommended: recommended[key]?.count || 0,
    }))
    .sort((a, b) => b.asked + b.recommended - (a.asked + a.recommended));
  return (
    <>
      <div className="dash-grid main-side">
        <Card title="Parks: asked about vs recommended" subtitle="Named in the question, against suggested in the answer. A gap shows where the desk steers visitors.">
          <PairedBars
            rows={rows}
            limit={14}
            series={[
              { key: "asked", label: "Asked about", color: "var(--viz-1)" },
              { key: "recommended", label: "Recommended", color: "var(--viz-2)" },
            ]}
            empty="No park named yet."
          />
        </Card>
        <Card title="Topics" subtitle="What the question was about">
          <BarList items={data.intents.map((item) => ({ ...item, label: label(item.key) }))} limit={12} onSelect={(item) => go("questions", { intent: item.key })} />
        </Card>
      </div>
      <Card title="Top questions" subtitle="The most repeated questions, grouped by wording">
        {data.top_questions.length ? (
          <div className="table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th scope="col">Question</th>
                  <th scope="col">Topic</th>
                  <th scope="col" className="num">Times asked</th>
                  <th scope="col" className="num">Answered</th>
                </tr>
              </thead>
              <tbody>
                {data.top_questions.map((item) => (
                  <tr key={item.question}>
                    <td>
                      <button type="button" className="dash-link left" onClick={() => go("questions", { q: item.question.slice(0, 60) })}>
                        {item.question}
                      </button>
                    </td>
                    <td>{label(item.intent)}</td>
                    <td className="num">{number(item.count)}</td>
                    <td className="num">{percent(item.answer_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No question has been repeated yet.</Empty>
        )}
      </Card>
      <div className="dash-grid three">
        <Card title="Wildlife asked about">
          <BarList items={data.animals.map((item) => ({ ...item, label: label(item.key) }))} empty="No animals named yet." />
        </Card>
        <Card title="Fee categories asked">
          <BarList items={data.fee_categories.map((item) => ({ ...item, label: label(item.key) }))} empty="No fee questions yet." />
        </Card>
        <Card title="Outside TANAPA's remit" subtitle="Pointed to NCAA, TAWA or Zanzibar">
          <BarList items={data.out_of_scope} empty="None in this period." />
        </Card>
      </div>
    </>
  );
}

function Quality({ data, go }) {
  const [gapOffset, setGapOffset] = useState(0);
  const latency = data.latency;
  const confidence = ordered(data.confidence, CONFIDENCE_ORDER).map((item, index) => ({
    ...item,
    label: label(item.key.toLowerCase()),
    // Ordinal blue ramp; the light end stays at step 250 so it clears 2:1 on the card.
    color: ["#1c5cab", "#3987e5", "#86b6ef"][index],
    ink: index === 2 ? "#0b0b0b" : null,
  }));
  return (
    <>
      <div className="kpi-band four">
        <StatTile label="Answer rate" value={percent(data.kpis.current.answer_rate)} current={data.kpis.current.answer_rate} previous={data.kpis.previous.answer_rate} kind="share" />
        <StatTile label="Median response" value={ms(latency.p50)} current={latency.p50} previous={data.kpis.previous.median_latency_ms} goodWhen="down" />
        <StatTile label="90th percentile" value={ms(latency.p90)} hint={`99th: ${ms(latency.p99)} · slowest ${ms(latency.max)}`} />
        <StatTile label="Mean confidence" value={percent(data.kpis.current.mean_confidence)} current={data.kpis.current.mean_confidence} previous={data.kpis.previous.mean_confidence} kind="share" />
      </div>
      <div className="dash-grid main-side">
        <Card title="Median response time per day" subtitle="Seconds from question to the full answer">
          <TimeSeries
            rows={data.series}
            series={[{ key: "median_latency_ms", label: "Median response", color: "var(--viz-1)", area: true }]}
            label="Median response time per day"
            height={220}
            format={ms}
            axisFormat={(value) => (value >= 1000 ? `${Math.round(value / 100) / 10}s` : `${Math.round(value)}ms`)}
          />
        </Card>
        <Card title="How questions ended">
          <OutcomePanel outcomes={data.outcomes} />
        </Card>
      </div>
      <Card
        title="Knowledge gaps"
        subtitle="Questions the desk declined, failed or answered with low confidence. Each one is content worth adding."
        actions={
          <button type="button" className="dash-link" onClick={() => go("questions", { outcome: "abstained" })}>
            All declined →
          </button>
        }
      >
        {data.gaps.length ? (
          <>
            <div className="table-wrap">
              <table className="dash-table">
                <thead>
                  <tr>
                    <th scope="col">Question</th>
                    <th scope="col">Topic</th>
                    <th scope="col" className="num">Times</th>
                    <th scope="col">Last asked</th>
                  </tr>
                </thead>
                <tbody>
                  {data.gaps.slice(gapOffset, gapOffset + GAP_PAGE).map((gap) => (
                    <tr key={gap.question + gap.last_at}>
                      <td>
                        <button type="button" className="dash-link left" onClick={() => go("questions", { q: gap.question.slice(0, 60) })}>
                          {gap.question}
                        </button>
                      </td>
                      <td>{label(gap.intent)}</td>
                      <td className="num">{gap.count}</td>
                      <td className="nowrap">{dateTime(gap.last_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.gaps.length} limit={GAP_PAGE} offset={gapOffset} onChange={setGapOffset} />
          </>
        ) : (
          <Empty>No gaps in this period. Every question was answered from the sources.</Empty>
        )}
      </Card>
      <div className="dash-grid two">
        <Card title="Answer confidence" subtitle="High to low">
          <SegmentedBar variant="tall" parts={confidence} label="Answers by confidence" />
        </Card>
        <Card title="Tools the agent used">
          <BarList items={data.tools.map((item) => ({ ...item, label: item.key.replace(/_/g, " ") }))} empty="No tool calls yet." />
        </Card>
      </div>
    </>
  );
}

export default function Insights({ days, params, go }) {
  const { data, error, loading } = useQuery(queries.overview(days));
  const tab = TABS.some(([id]) => id === params.tab) ? params.tab : "demand";
  if (!data) return error ? <ErrorNote error={error} /> : <Skeleton layout="insights" />;
  const View = { demand: Demand, audience: Audience, content: Content, quality: Quality }[tab];
  return (
    <div className={`dash-stack ${loading ? "refreshing" : ""}`}>
      <ErrorNote error={error} />
      <Tabs label="Insight views" tabs={TABS} value={tab} onChange={(id) => go("insights", { tab: id })} />
      <View data={data} go={go} />
    </div>
  );
}
