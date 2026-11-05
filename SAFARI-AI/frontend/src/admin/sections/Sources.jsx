import { useState } from "react";
import { fetchHarvests, fetchStatus, runHarvest } from "../api";
import { useLoad } from "../charts";
import { ago, dateTime, label, number } from "../format";
import { Card, Empty, ErrorNote, Status, sourceTone } from "../ui";

function records(value) {
  if (value == null) return "—";
  if (typeof value !== "object") return number(value);
  return (
    Object.entries(value)
      .filter(([, count]) => count)
      .map(([key, count]) => `${number(count)} ${key.replace(/_/g, " ")}`)
      .join(" · ") || "—"
  );
}

export default function Sources() {
  const status = useLoad(fetchStatus, []);
  const history = useLoad(fetchHarvests, []);
  const [running, setRunning] = useState("");
  const [notice, setNotice] = useState("");

  async function sync(full) {
    if (full && !window.confirm("A full harvest downloads every TANAPA publication and official page. It takes about a minute. Continue?")) return;
    setRunning(full ? "full" : "api");
    setNotice(full ? "Full harvest running: API, publications, official pages…" : "Syncing the TANAPA API…");
    try {
      const result = await runHarvest(full);
      setNotice(result.message);
    } catch (failure) {
      setNotice(failure.message);
    } finally {
      setRunning("");
      status.reload();
      history.reload();
    }
  }

  const data = status.data;

  return (
    <div className="dash-stack">
      <Card
        title="Sync with tanzaniaparks.go.tz"
        subtitle="The server syncs the TANAPA API on a schedule. Run it now after TANAPA publishes new fees or pages."
        actions={
          <>
            <button type="button" className="dash-button primary" disabled={Boolean(running)} onClick={() => sync(false)}>
              {running === "api" ? "Syncing…" : "Sync fees & parks"}
            </button>
            <button type="button" className="dash-button" disabled={Boolean(running)} onClick={() => sync(true)}>
              {running === "full" ? "Harvesting…" : "Full harvest"}
            </button>
          </>
        }
      >
        {notice ? <p className="dash-notice" role="status">{notice}</p> : null}
        {data ? (
          <p className="dash-meta">
            {number(data.documents)} documents · {number(data.chunks)} chunks · {number(data.parks)} parks · {number(data.tariff_rows)} fee rows · store {data.store} · LLM{" "}
            {data.llm_enabled ? `on (${data.llm_model})` : "off"}
          </p>
        ) : null}
      </Card>

      <ErrorNote error={status.error} />
      <Card title="Sources" className={status.loading ? "refreshing" : ""}>
        {data?.sources?.length ? (
          <div className="table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">State</th>
                  <th scope="col">Last success</th>
                  <th scope="col">Last attempt</th>
                  <th scope="col">Records</th>
                </tr>
              </thead>
              <tbody>
                {data.sources.map((source) => (
                  <tr key={source.id}>
                    <td>
                      {source.url ? (
                        <a href={source.url} target="_blank" rel="noreferrer" className="dash-link left">
                          {source.name || source.id}
                        </a>
                      ) : (
                        <strong>{source.name || source.id}</strong>
                      )}
                      {source.error ? <span className="cell-sub error-text">{source.error}</span> : null}
                    </td>
                    <td>
                      <Status tone={sourceTone(source.status)}>{source.status || "unknown"}</Status>
                    </td>
                    <td className="nowrap">
                      {dateTime(source.last_success)}
                      <span className="cell-sub">{ago(source.last_success)}</span>
                    </td>
                    <td className="nowrap">{dateTime(source.last_attempt)}</td>
                    <td className="records">{records(source.records)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No source has been harvested yet. Run a full harvest.</Empty>
        )}
      </Card>

      <Card title="Sync history" subtitle="Scheduled and manual runs since harvest logging began">
        {history.data && history.data.length ? (
          <div className="table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Trigger</th>
                  <th scope="col">Result</th>
                  <th scope="col" className="num">Fee rows</th>
                  <th scope="col" className="num">Parks</th>
                  <th scope="col" className="num">Took</th>
                </tr>
              </thead>
              <tbody>
                {history.data.map((run) => (
                  <tr key={run.at + run.kind}>
                    <td className="nowrap">{dateTime(run.at)}</td>
                    <td>{run.kind === "full" ? "Full harvest" : "API sync"}</td>
                    <td>{label(run.trigger)}</td>
                    <td>
                      <Status tone={sourceTone(run.status)}>{run.status}</Status>
                      {run.error ? <span className="cell-sub error-text">{run.error}</span> : null}
                    </td>
                    <td className="num">{number(run.tariff_rows)}</td>
                    <td className="num">{number(run.parks)}</td>
                    <td className="num">{run.duration_s != null ? `${run.duration_s} s` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No syncs recorded yet.</Empty>
        )}
      </Card>
    </div>
  );
}
