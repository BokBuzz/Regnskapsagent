import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle2, PieChart, Receipt, TrendingDown, TrendingUp } from "lucide-react";
import { Amount, EmptyState, ErrorBox, Loading, PageHead, YearSelect } from "../components/ui";
import { useAuth } from "../lib/auth";
import { useLoad } from "../lib/useLoad";

const inRange = (acc: string, from: number, to: number) => {
  const n = Number(acc.slice(0, 4));
  return n >= from && n <= to;
};

export default function ReportPage() {
  const { cid = "" } = useParams();
  const { api } = useAuth();
  const [year, setYear] = useState(new Date().getFullYear());
  const { data, error, loading } = useLoad(
    () => api.trialBalance(cid, `${year}-01-01`, `${year}-12-31`),
    [api, cid, year],
  );

  const sum = (from: number, to: number) =>
    (data?.accounts ?? []).filter((a) => inRange(a.account, from, to)).reduce((s, a) => s + a.balance_ore, 0);
  const income = -sum(3000, 3999);
  const costs = sum(4000, 7999);
  const result = -sum(3000, 8999);
  const vat = -sum(2700, 2740); // positivt = skyldig, negativt = til gode

  return (
    <div className="stack">
      <PageHead eyebrow={`Regnskapsåret ${year}`} title="Oversikt" action={<YearSelect year={year} onChange={setYear} />} />
      <ErrorBox error={error} />
      {loading ? (
        <Loading rows={2} />
      ) : !data?.accounts.length ? (
        <EmptyState icon={<PieChart size={34} />} title={`Ingen bokføringer i ${year}`}
          action={<Link className="button primary" to={`/c/${cid}/opplasting`}>Last opp kvittering</Link>}>
          Tallene dine vises her så snart du har bokført det første bilaget.
        </EmptyState>
      ) : (
        <>
          <div className="tiles">
            <div className="tile wide">
              <div className="label">Resultat hittil (foreløpig)</div>
              <div className="value"><Amount ore={result} /> kr</div>
            </div>
            <div className="tile">
              <div className="label"><TrendingUp size={14} /> Inntekter</div>
              <div className="value"><Amount ore={income} /></div>
            </div>
            <div className="tile">
              <div className="label"><TrendingDown size={14} /> Kostnader</div>
              <div className="value"><Amount ore={costs} /></div>
            </div>
            <div className="tile" style={{ gridColumn: "1 / -1" }}>
              <div className="label"><Receipt size={14} /> {vat >= 0 ? "MVA å betale" : "MVA til gode"}</div>
              <div className="value"><Amount ore={Math.abs(vat)} /></div>
            </div>
          </div>
          <section className="card stack" style={{ padding: 0 }}>
            <div className="spread" style={{ padding: "16px 18px 0" }}>
              <h2>Saldobalanse</h2>
              {data.total_ore === 0 && <span className="badge ok"><CheckCircle2 size={13} /> I balanse</span>}
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Konto</th><th className="right">Saldo</th></tr>
                </thead>
                <tbody>
                  {data.accounts.map((a) => (
                    <tr key={a.account}>
                      <td><span className="acc-no">{a.account}</span>{a.name}</td>
                      <td className="right"><Amount ore={a.balance_ore} /></td>
                    </tr>
                  ))}
                  <tr className="total">
                    <td>Sum (skal være 0)</td>
                    <td className="right"><Amount ore={data.total_ore} /></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
