import { useState } from "react";
import { fetchEvaluation, fetchSystem, runEvaluation } from "../api";
import { useLoad } from "../charts";
import { bytes, dateTime, duration, label, ms, number, percent } from "../format";
import { Card, Empty, ErrorNote, Status } from "../ui";

function check(value) {
  if (value === null || value === undefined) return "—";
  return value ? <Status tone="ok">pass</Status> : <Status tone="critical">fail</Status>;
}

export default function System() {
  const system = useLoad(fetchSystem, []);
  const evaluation = useLoad(fetchEvaluation, []);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);

  async function evaluate() {
    setRunning(true);
    setRunError(null);
    try {
      await runEvaluation();
      evaluation.reload();
    } catch (failure) {
      setRunError(failure);
    } finally {
      setRunning(false);
    }
  }

  const info = system.data;
  const result = evaluation.data;
  const hasResult = result && result.questions;

  return (
    <div className="dash-stack">
      <ErrorNote error={system.error || runError} />
      <Card
        title="Answer quality check"
        subtitle="Runs the expert question set against the desk (composer, no LLM) and checks declines, park recall, citations and expected content."
        actions={
          <button type="button" className="dash-button primary" disabled={running} onClick={evaluate}>
            {running ? "Running…" : "Run quality check"}
          </button>
        }
      >
        {hasResult ? (
          <>
            <div className="stat-grid four">
              <div className="stat-tile"><span className="stat-label">Correct declines</span><span className="stat-value">{percent(result.abstain_accuracy)}</span><span className="stat-hint">declines when it should, answers when it can</span></div>
              <div className="stat-tile"><span className="stat-label">Park recall</span><span className="stat-value">{percent(result.mean_park_recall)}</span><span className="stat-hint">expected parks recommended</span></div>
              <div className="stat-tile"><span className="stat-label">Citation rate</span><span className="stat-value">{percent(result.citation_rate)}</span><span className="stat-hint">answers that cite a source</span></div>
              <div className="stat-tile"><span className="stat-label">Expected content</span><span className="stat-value">{percent(result.contains_accuracy)}</span><span className="stat-hint">{`${result.questions} questions · ${ms(result.mean_latency_ms)} mean`}</span></div>
            </div>
            <p className="dash-meta">Last run {dateTime(result.ran_at)}</p>
            <details>
              <summary>Per-question results</summary>
              <div className="table-wrap">
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th scope="col">Question id</th>
                      <th scope="col">Intent</th>
                      <th scope="col">Decline check</th>
                      <th scope="col">Content check</th>
                      <th scope="col" className="num">Park recall</th>
                      <th scope="col">Cited</th>
                      <th scope="col">Confidence</th>
                      <th scope="col" className="num">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row) => (
                      <tr key={row.id}>
                        <td><code>{row.id}</code></td>
                        <td>{label(row.intent)}</td>
                        <td>{check(row.abstain_ok)}</td>
                        <td>{check(row.contains_ok)}</td>
                        <td className="num">{row.park_recall != null ? percent(row.park_recall) : "—"}</td>
                        <td>{row.cited ? "yes" : "no"}</td>
                        <td>{row.confidence_label}</td>
                        <td className="num">{ms(row.latency_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        ) : (
          <Empty>No quality check has been run yet.</Empty>
        )}
      </Card>

      {info ? (
        <div className="dash-grid two">
          <Card title="Configuration" subtitle="Read from the server environment (backend/.env)">
            <dl className="kv-grid">
              <div><dt>LLM agent</dt><dd>{info.llm_enabled ? <Status tone="ok">{info.llm_model}</Status> : <Status tone="warning">off</Status>}</dd></div>
              <div><dt>LLM endpoint</dt><dd>{info.llm_base_url || "default"}</dd></div>
              <div><dt>Store</dt><dd>{info.store}</dd></div>
              <div><dt>Auto-sync</dt><dd>{info.refresh_hours ? `every ${info.refresh_hours} h` : "off"}</dd></div>
              <div><dt>Exchange rate</dt><dd>{number(info.tzs_per_usd)} TZS / USD</dd></div>
              <div><dt>Rate limit</dt><dd>{info.rate_limit.limit} questions / {info.rate_limit.window_s} s per client</dd></div>
              <div><dt>Admin login</dt><dd>{info.admin_login_set ? <Status tone="ok">username and password set</Status> : <Status tone="warning">not set</Status>}</dd></div>
              <div><dt>Admin token</dt><dd>{info.admin_token_set ? <Status tone="ok">set</Status> : <Status tone="warning">not set, local only</Status>}</dd></div>
            </dl>
          </Card>
          <Card title="Server">
            <dl className="kv-grid">
              <div><dt>Version</dt><dd>{info.version}</dd></div>
              <div><dt>Python</dt><dd>{info.python}</dd></div>
              <div><dt>Up for</dt><dd>{duration(info.uptime_s)}</dd></div>
              <div><dt>Started</dt><dd>{dateTime(info.started_at)}</dd></div>
              <div><dt>Live chat sessions</dt><dd>{number(info.sessions_in_memory)}</dd></div>
              <div><dt>Question log</dt><dd>{bytes(info.event_log_bytes)}</dd></div>
              <div className="wide"><dt>Data folder</dt><dd><code>{info.data_dir}</code></dd></div>
            </dl>
          </Card>
        </div>
      ) : null}

      {info ? (
        <Card title="Data files">
          <div className="table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col" className="num">Size</th>
                  <th scope="col">Modified</th>
                </tr>
              </thead>
              <tbody>
                {info.data_files.map((file) => (
                  <tr key={file.path}>
                    <td><code>{file.path}</code></td>
                    <td className="num">{bytes(file.bytes)}</td>
                    <td>{dateTime(file.modified)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
