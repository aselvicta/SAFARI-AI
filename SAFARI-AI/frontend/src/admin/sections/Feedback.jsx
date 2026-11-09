import { useEffect, useState } from "react";
import { queries, reviewFeedback } from "../api";
import { useQuery } from "../charts";
import { invalidate } from "../data";
import { dateTime, number, percent } from "../format";
import { Card, Empty, ErrorNote, Pager, Select, Skeleton, StatTile, Status } from "../ui";

const LIMIT = 25;
const REVIEW_TONE = { open: "warning", reviewed: "info", resolved: "ok", dismissed: "neutral" };

export default function Feedback({ days }) {
  const [status, setStatus] = useState("");
  const [rating, setRating] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [days, status, rating]);
  const { data, error, loading, reload } = useQuery(queries.feedback({ days, status, rating, limit: LIMIT, offset }));
  const [notes, setNotes] = useState({});
  const [saving, setSaving] = useState("");
  const [saveError, setSaveError] = useState(null);

  async function review(item, next) {
    setSaving(item.id);
    setSaveError(null);
    try {
      await reviewFeedback(item.id, next, notes[item.id] ?? item.review_note);
      invalidate("feedback", "overview");
      reload();
    } catch (failure) {
      setSaveError(failure);
    } finally {
      setSaving("");
    }
  }

  const counts = data?.counts;
  const rated = counts ? counts.positive + counts.negative : 0;

  return (
    <div className="dash-stack">
      {counts ? (
        <div className="stat-grid four">
          <StatTile label="Ratings" value={number(counts.total)} />
          <StatTile label="Helpful" value={number(counts.positive)} hint={rated ? `${percent(counts.positive / rated)} of ratings` : ""} />
          <StatTile label="Not helpful" value={number(counts.negative)} hint={rated ? `${percent(counts.negative / rated)} of ratings` : ""} />
          <StatTile label="Waiting for review" value={number(counts.open)} />
        </div>
      ) : null}
      <div className="filter-row">
        <Select label="Rating" value={rating} onChange={setRating} options={[["", "Any rating"], ["-1", "Not helpful"], ["1", "Helpful"]]} />
        <Select label="Review" value={status} onChange={setStatus} options={[["", "Any state"], "open", "reviewed", "resolved", "dismissed"]} />
      </div>
      <ErrorNote error={error || saveError} />
      <Card title="Visitor feedback" subtitle="Thumbs up or down from the visitor desk, newest first." className={loading ? "refreshing" : ""}>
        {data && data.items.length ? (
          <ul className="feedback-list">
            {data.items.map((item) => (
              <li key={item.id} className="feedback-item">
                <div className="feedback-head">
                  <Status tone={item.rating === 1 ? "ok" : item.rating === -1 ? "critical" : "neutral"}>
                    {item.rating === 1 ? "Helpful" : item.rating === -1 ? "Not helpful" : "Neutral"}
                  </Status>
                  <Status tone={REVIEW_TONE[item.review_status]}>{item.review_status}</Status>
                  <span className="feedback-at">{dateTime(item.at)}</span>
                </div>
                <p className="feedback-question">{item.question || "(no question recorded)"}</p>
                {item.comment ? <blockquote>{item.comment}</blockquote> : null}
                {item.answer ? (
                  <details>
                    <summary>Answer the visitor saw</summary>
                    <pre className="feedback-answer">{item.answer}</pre>
                  </details>
                ) : null}
                <div className="feedback-actions">
                  <label className="dash-field grow">
                    <span>Admin note</span>
                    <input
                      value={notes[item.id] ?? item.review_note}
                      onChange={(event) => setNotes((current) => ({ ...current, [item.id]: event.target.value }))}
                      placeholder="What was wrong, what changed"
                    />
                  </label>
                  {["reviewed", "resolved", "dismissed"].map((next) => (
                    <button key={next} type="button" className="dash-button" disabled={saving === item.id} onClick={() => review(item, next)}>
                      {next === "reviewed" ? "Mark reviewed" : next === "resolved" ? "Resolved" : "Dismiss"}
                    </button>
                  ))}
                  {item.review_status !== "open" ? (
                    <button type="button" className="dash-link" onClick={() => review(item, "open")}>
                      Reopen
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : data ? (
          <Empty>No feedback matches these filters.</Empty>
        ) : error ? null : (
          <Skeleton layout="table" />
        )}
        {data ? <Pager total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} newer="← Newer" older="Older →" /> : null}
      </Card>
    </div>
  );
}
