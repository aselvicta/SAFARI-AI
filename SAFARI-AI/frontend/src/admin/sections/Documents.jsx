import { useState } from "react";
import { deleteDocument, fetchDocuments, fetchInventory, uploadDocument } from "../api";
import { BarList, useLoad } from "../charts";
import { compact, dateTime, label, number } from "../format";
import { Card, Empty, ErrorNote, Search, Select, Status } from "../ui";

const TYPES = ["", "tariff", "guideline", "procedure", "brochure", "regulation", "manual", "newsletter", "act", "policy"];

export default function Documents() {
  const { data, error, loading, reload } = useLoad(fetchDocuments, []);
  const inventory = useLoad(fetchInventory, []);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [authority, setAuthority] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function upload(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const file = values.get("file");
    if (!(file instanceof File) || !file.name) return;
    const metadata = {};
    for (const key of ["title", "document_type", "effective_from", "effective_until", "status", "authority", "organization"]) {
      const value = values.get(key);
      if (value) metadata[key] = value;
    }
    setBusy(true);
    setNotice("Indexing…");
    try {
      const result = await uploadDocument(file, metadata);
      setNotice(`Indexed ${result.title} as a ${result.document_type}.`);
      form.reset();
      reload();
      inventory.reload();
    } catch (failure) {
      setNotice(failure.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(document) {
    if (!window.confirm(`Remove “${document.title}” from the index? Visitors will no longer get answers from it. A later harvest may add it back if it is still published.`)) return;
    try {
      const result = await deleteDocument(document.document_id);
      setNotice(result.message);
      reload();
      inventory.reload();
    } catch (failure) {
      setNotice(failure.message);
    }
  }

  const documents = data || [];
  const needle = search.trim().toLowerCase();
  const shown = documents.filter(
    (document) =>
      (!needle || `${document.title} ${document.organization} ${document.document_id}`.toLowerCase().includes(needle)) &&
      (!type || document.document_type === type) &&
      (!authority || document.authority === authority),
  );
  const stock = inventory.data;

  return (
    <div className="dash-stack">
      {stock ? (
        <div className="dash-grid three">
          <Card title="By type">
            <BarList items={stock.documents_by_type.map((item) => ({ ...item, label: label(item.key) }))} onSelect={(item) => setType(item.key)} />
          </Card>
          <Card title="By publisher">
            <BarList items={stock.documents_by_org} />
          </Card>
          <Card title="By authority">
            <BarList items={stock.documents_by_authority.map((item) => ({ ...item, label: label(item.key) }))} onSelect={(item) => setAuthority(item.key)} />
          </Card>
        </div>
      ) : null}

      {stock && stock.needs_ocr.length ? (
        <Card title="Scanned PDFs waiting for text" subtitle="These TANAPA publications have no text layer, so they are not searchable. Upload a text or OCR'd version below.">
          <ul className="plain-list">
            {stock.needs_ocr.map((title) => (
              <li key={title}>
                <Status tone="info">needs OCR</Status> {title}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card title="Add a document" subtitle="PDF, text or Markdown, up to 25 MB. It is split into chunks and searchable straight away.">
        <form className="dash-form" onSubmit={upload}>
          <label className="dash-field wide">
            <span>File</span>
            <input name="file" type="file" required accept=".pdf,.txt,.md" />
          </label>
          <label className="dash-field">
            <span>Title</span>
            <input name="title" placeholder="TANAPA Park Tariffs" />
          </label>
          <label className="dash-field">
            <span>Publisher</span>
            <input name="organization" placeholder="TANAPA" />
          </label>
          <label className="dash-field">
            <span>Type</span>
            <select name="document_type" defaultValue="">
              {TYPES.map((item) => (
                <option key={item} value={item}>
                  {item ? label(item) : "Detect from text"}
                </option>
              ))}
            </select>
          </label>
          <label className="dash-field">
            <span>Authority</span>
            <select name="authority" defaultValue="official">
              <option value="official">Official</option>
              <option value="expert">Expert</option>
              <option value="unverified">Unverified</option>
            </select>
          </label>
          <label className="dash-field">
            <span>Status</span>
            <select name="status" defaultValue="current">
              <option value="current">Current</option>
              <option value="superseded">Superseded</option>
            </select>
          </label>
          <label className="dash-field">
            <span>Effective from</span>
            <input name="effective_from" type="date" />
          </label>
          <label className="dash-field">
            <span>Effective until</span>
            <input name="effective_until" type="date" />
          </label>
          <button type="submit" className="dash-button primary" disabled={busy}>
            {busy ? "Indexing…" : "Index document"}
          </button>
        </form>
        {notice ? <p className="dash-notice" role="status">{notice}</p> : null}
      </Card>

      <div className="filter-row">
        <Search value={search} onChange={setSearch} placeholder="Title, publisher or id" />
        <Select label="Type" value={type} onChange={setType} options={[["", "All types"], ...[...new Set(documents.map((item) => item.document_type))].sort()]} />
        <Select label="Authority" value={authority} onChange={setAuthority} options={[["", "Any authority"], ...[...new Set(documents.map((item) => item.authority))].sort()]} />
      </div>
      <ErrorNote error={error} />
      <Card title={`${shown.length} of ${documents.length} documents`} className={loading ? "refreshing" : ""}>
        {shown.length ? (
          <div className="table-wrap tall">
            <table className="dash-table">
              <thead>
                <tr>
                  <th scope="col">Document</th>
                  <th scope="col">Type</th>
                  <th scope="col">Authority</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">Chunks</th>
                  <th scope="col">Retrieved</th>
                  <th scope="col"><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((document) => (
                  <tr key={document.document_id}>
                    <td>
                      {document.source_url ? (
                        <a href={document.source_url} target="_blank" rel="noreferrer" className="dash-link left">
                          {document.title}
                        </a>
                      ) : (
                        <strong>{document.title}</strong>
                      )}
                      <span className="cell-sub">
                        {document.organization} · {document.document_id}
                        {document.effective_from || document.effective_until ? ` · ${document.effective_from || "—"} → ${document.effective_until || "—"}` : ""}
                      </span>
                    </td>
                    <td>{label(document.document_type)}</td>
                    <td>{label(document.authority)}</td>
                    <td>
                      <Status tone={document.status === "current" ? "ok" : "neutral"}>{document.status}</Status>
                    </td>
                    <td className="num">
                      {number(document.chunks)}
                      <span className="cell-sub">{compact(document.characters)} chars</span>
                    </td>
                    <td className="nowrap">{dateTime(document.retrieved_at)}</td>
                    <td>
                      <button type="button" className="dash-link danger" onClick={() => remove(document)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No documents match.</Empty>
        )}
      </Card>
    </div>
  );
}
