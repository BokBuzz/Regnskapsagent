import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Printer } from "lucide-react";
import { Amount, ErrorBox, Loading } from "../components/ui";
import { useAuth } from "../lib/auth";
import { formatDate } from "../lib/money";
import { useLoad } from "../lib/useLoad";

/** Lønnsslipp for én ansatt. Kan skrives ut eller lagres som PDF fra nettleseren. */
export default function PayslipPage() {
  const { cid = "", rid = "", eid = "" } = useParams();
  const { api } = useAuth();
  const { data: p, error } = useLoad(() => api.payslip(cid, rid, eid), [api, cid, rid, eid]);
  if (!p) return error ? <ErrorBox error={error} /> : <Loading rows={4} />;
  const ln = p.line;
  const row = (label: string, ore: number, strong = false) => (
    <tr className={strong ? "total" : undefined}><td>{label}</td><td className="right"><Amount ore={ore} /></td></tr>
  );
  return (
    <div className="stack">
      <div className="spread no-print">
        <Link to={`/c/${cid}/lonn/${rid}`} className="muted row" style={{ gap: 6 }}><ArrowLeft size={16} /> Tilbake</Link>
        <button className="ghost" onClick={() => window.print()}><Printer size={16} /> Skriv ut</button>
      </div>
      <section className="card stack">
        <div className="spread">
          <div>
            <span className="acc-no">{p.company.name} · org.nr {p.company.orgnr}</span>
            <h2>Lønnsslipp {p.period}</h2>
          </div>
          {p.run.status !== "approved" && <span className="badge honey">Utkast</span>}
        </div>
        <div>
          <strong>{ln.name}</strong>
          <div className="muted">Utbetales {formatDate(p.run.pay_date)}</div>
        </div>
        <table>
          <tbody>
            {row(ln.pay_type === "hourly" && ln.hours_x100 != null
              ? `Timelønn ${(ln.hours_x100 / 100).toLocaleString("nb-NO")} t` : "Fastlønn", ln.base_ore)}
            {ln.bonus_ore > 0 && row("Tillegg", ln.bonus_ore)}
            {row("Bruttolønn", ln.gross_ore, true)}
            {row(ln.tax_card_kind === "percent" ? `Forskuddstrekk ${ln.tax_percent} %`
              : ln.tax_card_kind === "table" ? `Forskuddstrekk tabell ${ln.tax_table}` : "Forskuddstrekk", -ln.tax_ore)}
            {row("Til utbetaling", ln.net_ore, true)}
          </tbody>
        </table>
        <table>
          <thead><tr><th>Hittil i år</th><th /></tr></thead>
          <tbody>
            {row("Brutto", p.year_to_date.gross)}
            {row("Forskuddstrekk", p.year_to_date.tax)}
            {row("Opptjente feriepenger", p.year_to_date.holiday)}
          </tbody>
        </table>
      </section>
    </div>
  );
}
