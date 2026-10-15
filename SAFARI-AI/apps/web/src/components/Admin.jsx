import { useEffect, useState } from "react";
import { fetchDocuments, fetchStatus, runHarvest, uploadDocument } from "../api";
import { formatDate, formatNumber } from "../i18n";

const TYPES = ["", "tariff", "guideline", "procedure", "brochure", "regulation", "manual", "newsletter", "act", "policy"];
const TOKEN_KEY = "safari.adminToken";

function readToken() {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function saveToken(value) {
  try {
    window.sessionStorage.setItem(TOKEN_KEY, value);
  } catch {
    // Token stays in memory only.
  }
}

function formatRecords(records) {
  if (records == null) return "—";
  if (typeof records !== "object") return formatNumber(records);
  return Object.entries(records)
    .filter(([, value]) => value)
    .map(([key, value]) => `${formatNumber(value)} ${key.replace(/_/g, " ")}`)
    .join(" · ") || "—";
}

export default function Admin({ lang }) {
  const [token, setToken] = useState(readToken);
  const [status, setStatus] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [harvesting, setHarvesting] = useState(false);
  const [notice, setNotice] = useState("");
  const [uploadNotice, setUploadNotice] = useState("");

  async function refresh() {
    const [nextStatus, nextDocuments] = await Promise.all([fetchStatus(), fetchDocuments()]);
    setStatus(nextStatus);
    setDocuments(Array.isArray(nextDocuments) ? nextDocuments : []);
  }

  useEffect(() => {
    refresh();
  }, []);

  function changeToken(value) {
    setToken(value);
    saveToken(value);
  }

  async function harvest() {
    setHarvesting(true);
    setNotice("Refreshing sources…");
    try {
      const result = await runHarvest(token);
      setNotice(result.message || "Sources refreshed.");
      await refresh();
    } catch (error) {
      setNotice(error.message);
    } finally {
      setHarvesting(false);
    }
  }

  async function upload(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const file = data.get("file");
    if (!(file instanceof File) || !file.name) return;
    const metadata = {};
    for (const key of ["title", "document_type", "effective_from", "effective_until", "status", "authority"]) {
      const value = data.get(key);
      if (value) metadata[key] = value;
    }
    setUploadNotice("Indexing…");
    try {
      const result = await uploadDocument(token, file, metadata);
      setUploadNotice(`Indexed ${result.title} (${result.document_id}).`);
      form.reset();
      await refresh();
    } catch (error) {
      setUploadNotice(error.message);
    }
  }

  const sources = status?.sources || [];

  return (
    <main className="admin">
      <header className="admin-head">
        <a href="/" className="text-button">
          ← SafariAI
        </a>
        <h1 className="display big">Index &amp; sources</h1>
        <p>Source freshness, manual refresh and document uploads.</p>
      </header>

      <section className="admin-card">
        <label className="field" htmlFor="admin-token">
          <span>Admin token</span>
          <input
            id="admin-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => changeToken(event.target.value)}
            placeholder="Only needed when SAFARI_ADMIN_TOKEN is set"
          />
        </label>
      </section>

      <section className="admin-card">
        <div className="admin-row">
          <h2>Sources</h2>
          <button type="button" className="primary-button" onClick={harvest} disabled={harvesting}>
            {harvesting ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
        {notice ? <p className="admin-notice" role="status">{notice}</p> : null}
        {status ? (
          <p className="admin-meta">
            {formatNumber(status.documents)} documents · {formatNumber(status.chunks)} chunks · {formatNumber(status.parks)} parks ·
            store {status.store} · LLM {status.llm_enabled ? "on" : "off"}
          </p>
        ) : (
          <p className="admin-meta">Status is unavailable. Is the API running?</p>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Status</th>
                <th scope="col">Last success</th>
                <th scope="col" className="num">
                  Records
                </th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.id}>
                  <td>
                    <strong>{source.name || source.id}</strong>
                    {source.error ? <span className="fee-age">{source.error}</span> : null}
                  </td>
                  <td>
                    <span className={`badge badge-small ${source.status === "ok" ? "badge-ok" : "badge-warn"}`}>
                      {source.status || "unknown"}
                    </span>
                  </td>
                  <td>{source.last_success ? formatDate(source.last_success, lang) : "—"}</td>
                  <td className="records">{formatRecords(source.records)}</td>
                </tr>
              ))}
              {!sources.length ? (
                <tr>
                  <td colSpan={4}>No source has been harvested yet.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="admin-card">
        <h2>Add a document</h2>
        <form className="admin-form" onSubmit={upload}>
          <label className="field" htmlFor="admin-file">
            <span>PDF, text or Markdown</span>
            <input id="admin-file" name="file" type="file" required accept=".pdf,.txt,.md" />
          </label>
          <label className="field">
            <span>Title</span>
            <input name="title" placeholder="TANAPA Park Tariffs" />
          </label>
          <label className="field">
            <span>Type</span>
            <select name="document_type" defaultValue="">
              {TYPES.map((type) => (
                <option key={type} value={type}>
                  {type || "Detect"}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Effective from</span>
            <input name="effective_from" type="date" />
          </label>
          <label className="field">
            <span>Effective until</span>
            <input name="effective_until" type="date" />
          </label>
          <label className="field">
            <span>Status</span>
            <select name="status" defaultValue="current">
              <option value="current">current</option>
              <option value="superseded">superseded</option>
            </select>
          </label>
          <label className="field">
            <span>Authority</span>
            <select name="authority" defaultValue="official">
              <option value="official">official</option>
              <option value="unverified">unverified</option>
              <option value="expert">expert</option>
            </select>
          </label>
          <button type="submit" className="primary-button">
            Index document
          </button>
        </form>
        {uploadNotice ? <p className="admin-notice" role="status">{uploadNotice}</p> : null}
      </section>

      <section className="admin-card">
        <h2>Indexed documents ({documents.length})</h2>
        <ul className="doc-list">
          {documents.map((document) => (
            <li key={document.document_id}>
              <strong>{document.title}</strong>
              <span>
                {document.organization} · {document.document_type} · {document.status} · {document.authority}
                {document.effective_from || document.effective_until
                  ? ` · ${document.effective_from || "—"} – ${document.effective_until || "—"}`
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
