import { useState } from "react";
import { useParams } from "react-router-dom";
import { Amount, ErrorBox, Loading } from "../components/ui";
import { useAuth } from "../lib/auth";
import { useLoad } from "../lib/useLoad";

export default function ReportPage() {
  const { cid = "" } = useParams();
  const { api } = useAuth();
  const [year, setYear] = useState(new Date().getFullYear());
  const { data, error, loading } = useLoad(
    () => api.trialBalance(cid, `${year}-01-01`, `${year}-12-31`),
    [api, cid, year],
  );

  return (
    <div className="stack">
      <div className="spread">
        <h1>Saldobalanse</h1>
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
      ) : !data?.accounts.length ? (
        <p className="muted">Ingen bokføringer i {year}.</p>
      ) : (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr><th>Konto</th><th className="right">Saldo</th></tr>
            </thead>
            <tbody>
              {data.accounts.map((a) => (
                <tr key={a.account}>
                  <td>{a.account} {a.name}</td>
                  <td className="right"><Amount ore={a.balance_ore} /></td>
                </tr>
              ))}
              <tr>
                <td><strong>Sum (skal være 0)</strong></td>
                <td className="right"><strong><Amount ore={data.total_ore} /></strong></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
