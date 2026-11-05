import { useEffect, useState } from "react";
import { fetchParks } from "../../api";
import { fetchFees, fetchInventory } from "../api";
import { BarList, useLoad } from "../charts";
import { formatDay, label, number } from "../format";
import { Card, Empty, ErrorNote, Search, Select, Status } from "../ui";

const STATE_TONE = { in_force: "ok", upcoming: "info", expired: "neutral" };
const AGE_LABEL = { adult: "adult", child_5_15: "child 5–15", child_under_5: "child under 5" };
const VISITOR_LABEL = { non_resident: "Non-resident", expatriate: "Expatriate", eac_citizen: "EAC citizen", any: "Any" };

export default function Fees({ params }) {
  const [park, setPark] = useState(params.park || "");
  const [category, setCategory] = useState("");
  const [visitor, setVisitor] = useState("");
  const [state, setState] = useState("in_force");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [parks, setParks] = useState([]);
  const inventory = useLoad(fetchInventory, []);
  const { data, error, loading } = useLoad(() => fetchFees({ park, category, visitor, state, q, limit: 500 }), [park, category, visitor, state, q]);

  useEffect(() => {
    fetchParks().then((items) => setParks(Array.isArray(items) ? items : []));
  }, []);
  useEffect(() => setPark(params.park || ""), [params.park]);
  useEffect(() => {
    const timer = setTimeout(() => setQ(search), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const stock = inventory.data;

  return (
    <div className="dash-stack">
      {stock ? (
        <div className="dash-grid two">
          <Card title="Tariff windows" subtitle="Validity periods published on the TANAPA tariff API">
            <div className="table-wrap">
              <table className="dash-table">
                <thead>
                  <tr>
                    <th scope="col">Valid from</th>
                    <th scope="col">Valid until</th>
                    <th scope="col" className="num">Rows</th>
                    <th scope="col">State</th>
                  </tr>
                </thead>
                <tbody>
                  {stock.tariff_windows.map((window) => (
                    <tr key={`${window.valid_from}-${window.valid_until}`}>
                      <td>{window.valid_from ? formatDay(window.valid_from, true) + ` ${window.valid_from.slice(0, 4)}` : "—"}</td>
                      <td>{window.valid_until ? formatDay(window.valid_until, true) + ` ${window.valid_until.slice(0, 4)}` : "open"}</td>
                      <td className="num">{number(window.rows)}</td>
                      <td>
                        <Status tone={STATE_TONE[window.state]}>{label(window.state)}</Status>
                        {window.days_left != null ? <span className="cell-sub">{window.days_left} days left</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Fee rows in force by category">
            <BarList items={stock.fee_categories} limit={12} onSelect={(item) => setCategory(item.key)} />
          </Card>
        </div>
      ) : null}

      <div className="filter-row">
        <Select label="Park" value={park} onChange={setPark} options={[["", "All parks"], ...parks.map((item) => [item.slug, item.name])]} />
        <Select label="Category" value={category} onChange={setCategory} options={[["", "All categories"], ...(data?.categories || [])]} />
        <Select label="Visitor" value={visitor} onChange={setVisitor} options={[["", "All visitors"], ...(data?.visitors || []).map((item) => [item, VISITOR_LABEL[item] || label(item)])]} />
        <Select label="Validity" value={state} onChange={setState} options={[["", "Any"], ["in_force", "In force today"], ["upcoming", "Upcoming"], ["expired", "Expired"]]} />
        <Search value={search} onChange={setSearch} placeholder="Item, e.g. camping" />
      </div>
      <ErrorNote error={error} />
      <Card
        title={data ? `${number(data.total)} fee rows` : "Fee rows"}
        subtitle={data ? `Official TZS amounts. USD is approximate at ${number(data.tzs_per_usd)} TZS per USD.${data.total > data.rows.length ? ` Showing the first ${data.rows.length}.` : ""}` : ""}
        className={loading ? "refreshing" : ""}
      >
        {data && data.rows.length ? (
          <div className="table-wrap tall">
            <table className="dash-table">
              <thead>
                <tr>
                  <th scope="col">Park</th>
                  <th scope="col">Category</th>
                  <th scope="col">Item</th>
                  <th scope="col">Visitor</th>
                  <th scope="col">Season</th>
                  <th scope="col" className="num">TZS</th>
                  <th scope="col" className="num">≈ USD</th>
                  <th scope="col">Valid</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id}>
                    <td>{(row.park_name || "").replace(/ National Park$/, "")}</td>
                    <td>{row.category}</td>
                    <td>
                      {row.item}
                      <span className="cell-sub">{row.unit}</span>
                    </td>
                    <td>{VISITOR_LABEL[row.visitor] || row.visitor_label || row.visitor}{row.age && row.age !== "any" ? `, ${AGE_LABEL[row.age] || label(row.age)}` : ""}</td>
                    <td>{row.season_label || "—"}</td>
                    <td className="num">{number(row.amount)}</td>
                    <td className="num">{row.usd != null ? number(row.usd, 2) : "—"}</td>
                    <td className="nowrap">
                      {row.valid_from || "—"} → {row.valid_until || "open"}
                      {row.state !== "in_force" ? <span className="cell-sub">{label(row.state)}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : data ? (
          <Empty>No fee rows match these filters.</Empty>
        ) : null}
      </Card>
    </div>
  );
}
