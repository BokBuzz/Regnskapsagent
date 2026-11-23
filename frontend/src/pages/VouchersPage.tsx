import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorBox, Loading } from "../components/ui";
import { useAuth } from "../lib/auth";
import { formatDate } from "../lib/money";
import { useLoad } from "../lib/useLoad";

export default function VouchersPage() {
  const { cid = "" } = useParams();
  const { api } = useAuth();
  const [year, setYear] = useState(new Date().getFullYear());
  const { data, error, loading } = useLoad(() => api.vouchers(cid, year), [api, cid, year]);

  return (
    <div className="stack">
      <div className="spread">
        <h1>Bokførte bilag</h1>
        <select aria-label="År" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: "auto" }}>
          {[0, 1, 2].map((d) => {
            const y = new Date().getFullYear() - d;
            return <option key={y} value={y}>{y}</option>;
          })}
        </select>
      </div>
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : !data?.length ? (
        <p className="muted">Ingen bokførte bilag i {year}.</p>
      ) : (
        <div className="card list" style={{ padding: 0 }}>
          {[...data].reverse().map((v) => (
            <Link key={v.id} to={v.id} className="item">
              <span>
                <strong className="num">{v.series}{v.number}</strong> {v.description}
              </span>
              <span className="muted num">{formatDate(v.voucher_date)}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
