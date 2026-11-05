import { useState } from "react";
import { fetchInventory } from "../api";
import { BarList, Meter, useLoad } from "../charts";
import { label, number, percent } from "../format";
import { Card, ErrorNote, Search, Select, Status } from "../ui";

function range(values, unit) {
  if (!values) return "—";
  const [low, high] = values;
  const text = (value) => (unit === "USD" ? `USD ${number(value, 2)}` : `TZS ${number(value)}`);
  return low === high ? text(low) : `${text(low)} – ${text(high)}`;
}

export default function Parks({ go }) {
  const { data, error } = useLoad(fetchInventory, []);
  const [search, setSearch] = useState("");
  const [circuit, setCircuit] = useState("");
  const [sort, setSort] = useState("name");
  if (!data) return <ErrorNote error={error} />;

  const circuits = [...new Set(data.parks.map((park) => park.circuit).filter(Boolean))].sort();
  const needle = search.trim().toLowerCase();
  const parks = data.parks
    .filter((park) => (!needle || park.name.toLowerCase().includes(needle)) && (!circuit || park.circuit === circuit))
    .sort((a, b) => {
      if (sort === "area") return (b.area_km2 || 0) - (a.area_km2 || 0);
      if (sort === "fee") return ((b.nr_adult_entrance_tzs || [0])[1] || 0) - ((a.nr_adult_entrance_tzs || [0])[1] || 0);
      if (sort === "completeness") return a.completeness - b.completeness;
      return a.name.localeCompare(b.name);
    });
  const complete = data.parks.filter((park) => park.completeness >= 1).length;

  return (
    <div className="dash-stack">
      <div className="stat-grid four">
        <div className="stat-tile"><span className="stat-label">Parks</span><span className="stat-value">{data.parks.length}</span><span className="stat-hint">2024 TANAPA GIS map</span></div>
        <div className="stat-tile"><span className="stat-label">Complete profiles</span><span className="stat-value">{complete}</span><span className="stat-hint">{percent(complete / Math.max(1, data.parks.length))} have page, photo, contact, text and fees</span></div>
        <div className="stat-tile"><span className="stat-label">Activities</span><span className="stat-value">{data.totals.activities}</span><span className="stat-hint">from the TANAPA site</span></div>
        <div className="stat-tile"><span className="stat-label">Total protected area</span><span className="stat-value">{number(data.parks.reduce((sum, park) => sum + (park.area_km2 || 0), 0))} km²</span><span className="stat-hint">sum of park areas</span></div>
      </div>

      <div className="filter-row">
        <Search value={search} onChange={setSearch} placeholder="Park name" />
        <Select label="Circuit" value={circuit} onChange={setCircuit} options={[["", "All circuits"], ...circuits.map((item) => [item, label(item)])]} />
        <Select label="Sort by" value={sort} onChange={setSort} options={[["name", "Name"], ["area", "Area"], ["fee", "Entrance fee"], ["completeness", "Least complete first"]]} />
      </div>

      <Card title="National parks" subtitle={`Non-resident adult entrance fees in force on ${data.as_of}. Select a park to see its full tariff.`}>
        <div className="table-wrap">
          <table className="dash-table">
            <thead>
              <tr>
                <th scope="col">Park</th>
                <th scope="col">Circuit</th>
                <th scope="col" className="num">Area km²</th>
                <th scope="col" className="num">Est.</th>
                <th scope="col">NR adult entrance</th>
                <th scope="col" className="num">Fee rows</th>
                <th scope="col">Profile</th>
              </tr>
            </thead>
            <tbody>
              {parks.map((park) => (
                <tr key={park.slug}>
                  <td>
                    <div className="park-cell">
                      {park.image_url ? <img src={park.image_url} alt="" loading="lazy" width="56" height="40" /> : <span className="park-thumb-empty" />}
                      <span>
                        <button type="button" className="dash-link left" onClick={() => go("fees", { park: park.slug })}>
                          {park.name}
                        </button>
                        {park.page_url ? (
                          <a className="park-page" href={park.page_url} target="_blank" rel="noreferrer">
                            tanzaniaparks.go.tz ↗
                          </a>
                        ) : null}
                      </span>
                    </div>
                  </td>
                  <td>{label(park.circuit)}</td>
                  <td className="num">{number(park.area_km2)}</td>
                  <td className="num">{park.established_year || "—"}</td>
                  <td className="nowrap">
                    {range(park.nr_adult_entrance_tzs, "TZS")}
                    <span className="cell-sub">≈ {range(park.nr_adult_entrance_usd, "USD")}</span>
                  </td>
                  <td className="num">
                    {number(park.in_force_rows)}
                    <span className="cell-sub">of {number(park.tariff_rows)}</span>
                  </td>
                  <td>
                    <Meter value={park.completeness} label={`${park.name} profile completeness`} />
                    <span className="cell-flags">
                      {!park.has_profile ? <Status tone="warning">no page</Status> : null}
                      {park.has_profile && !park.has_image ? <Status tone="info">no photo</Status> : null}
                      {park.has_profile && !park.has_contact ? <Status tone="info">no contact</Status> : null}
                      {!park.in_force_rows ? <Status tone="critical">no fees</Status> : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="dash-grid two">
        <Card title="Area by park" subtitle="km², 2024 GIS map">
          <BarList items={[...data.parks].sort((a, b) => (b.area_km2 || 0) - (a.area_km2 || 0)).map((park) => ({ key: park.slug, label: park.name.replace(/ National Park$/, ""), count: park.area_km2 || 0 }))} limit={21} />
        </Card>
        <div className="dash-stack">
          <Card title="Activities on the site">
            <ul className="tag-list">
              {data.activities.map((title) => (
                <li key={title}>{title}</li>
              ))}
            </ul>
          </Card>
          <Card title="Accommodation types">
            <ul className="plain-list">
              {data.accommodation.map((item) => (
                <li key={item.title}>
                  <strong>{item.title}</strong>
                  <span>{item.price_range || ""}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
