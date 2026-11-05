import { fetchOverview } from "../api";
import { BarList, HourColumns, TimeSeries, useLoad } from "../charts";
import { dateTime, label, ms } from "../format";
import { Card, Empty, ErrorNote } from "../ui";

export default function Insights({ days, go }) {
  const { data, error, loading } = useLoad(() => fetchOverview(days), [days]);
  if (!data) return <ErrorNote error={error} />;
  const latency = data.latency;
  const titled = (items) => items.map((item) => ({ ...item, label: label(item.key) }));

  return (
    <div className={`dash-stack ${loading ? "refreshing" : ""}`}>
      <ErrorNote error={error} />
      <Card title="Unique visitor sessions per day">
        <TimeSeries rows={data.series} series={[{ key: "sessions", label: "Sessions", color: "var(--viz-1)", area: true }]} label="Visitor sessions per day" height={180} />
      </Card>

      <Card title="Knowledge gaps" subtitle="Questions the desk declined, failed or answered with low confidence. Each one is content worth adding.">
        {data.gaps.length ? (
          <div className="table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th scope="col">Question</th>
                  <th scope="col">Intent</th>
                  <th scope="col" className="num">Times</th>
                  <th scope="col">Last asked</th>
                </tr>
              </thead>
              <tbody>
                {data.gaps.map((gap) => (
                  <tr key={gap.question + gap.last_at}>
                    <td>
                      <button type="button" className="dash-link left" onClick={() => go("questions", { q: gap.question.slice(0, 60) })}>
                        {gap.question}
                      </button>
                    </td>
                    <td>{label(gap.intent)}</td>
                    <td className="num">{gap.count}</td>
                    <td>{dateTime(gap.last_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No gaps in this period. Every question was answered from the sources.</Empty>
        )}
      </Card>

      <div className="dash-grid two">
        <Card title="Parks visitors ask about" subtitle="Named in the question">
          <BarList items={data.parks} limit={21} empty="No park named yet." onSelect={(item) => go("questions", { park: item.key })} />
        </Card>
        <Card title="Parks the desk recommended" subtitle="Suggested in answers">
          <BarList items={data.recommended} limit={21} empty="No recommendations yet." />
        </Card>
      </div>

      <div className="dash-grid three">
        <Card title="Source markets" subtitle="Passport given in trip details">
          <BarList items={data.markets} empty="No passports given yet." />
        </Card>
        <Card title="Fee class">
          <BarList items={titled(data.visitor_classes)} />
        </Card>
        <Card title="Language">
          <BarList items={data.languages.map((item) => ({ ...item, label: item.key === "sw" ? "Kiswahili" : item.key === "en" ? "English" : item.key }))} />
        </Card>
      </div>

      <div className="dash-grid three">
        <Card title="Trip length">
          <BarList items={data.trip_length} empty="No trip lengths given yet." />
        </Card>
        <Card title="Group size">
          <BarList items={data.group_size} empty="No group sizes given yet." />
        </Card>
        <Card title="Fee categories asked">
          <BarList items={data.fee_categories} empty="No fee questions yet." />
        </Card>
      </div>

      <Card title="When visitors ask" subtitle="Questions by hour, East Africa Time">
        <HourColumns hours={data.hours} />
      </Card>

      <div className="dash-grid three">
        <Card title="Wildlife asked about">
          <BarList items={titled(data.animals)} empty="No animals named yet." />
        </Card>
        <Card title="Outside TANAPA's remit" subtitle="Pointed to NCAA, TAWA, Zanzibar">
          <BarList items={data.out_of_scope} empty="None in this period." />
        </Card>
        <Card title="Answer confidence">
          <BarList items={titled(data.confidence)} />
        </Card>
      </div>

      <div className="dash-grid two">
        <Card title="Tools the agent used">
          <BarList items={data.tools.map((item) => ({ ...item, label: item.key.replace(/_/g, " ") }))} empty="No tool calls yet." />
        </Card>
        <Card title="Response time">
          <dl className="kv-grid">
            <div><dt>Median</dt><dd>{ms(latency.p50)}</dd></div>
            <div><dt>90th percentile</dt><dd>{ms(latency.p90)}</dd></div>
            <div><dt>99th percentile</dt><dd>{ms(latency.p99)}</dd></div>
            <div><dt>Slowest</dt><dd>{ms(latency.max)}</dd></div>
            {Object.entries(latency.by_generator).map(([name, value]) => (
              <div key={name}><dt>Median, {name}</dt><dd>{ms(value)}</dd></div>
            ))}
          </dl>
        </Card>
      </div>
    </div>
  );
}
