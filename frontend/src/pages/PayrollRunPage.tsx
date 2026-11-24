import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Download, FileText, Pencil, ShieldCheck, Trash2 } from "lucide-react";
import { Amount, ErrorBox, Loading, Notice, PageHead } from "../components/ui";
import type { PayrollLine, PayrollSummary } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDate, formatOre, parseKroner } from "../lib/money";
import { useLoad } from "../lib/useLoad";
import { MONTHS, saveBlob } from "./PayrollPage";

/**
 * Én lønnskjøring. Utkastet kan endres (timer, tillegg, manuelt trekk). Godkjenning skjer i to steg:
 * først ser kunden lønnsbilaget, deretter bekrefter hun nøyaktig det hun så.
 */
export default function PayrollRunPage() {
  const { cid = "", rid = "" } = useParams();
  const { api } = useAuth();
  const load = useLoad(() => api.payrollRun(cid, rid), [api, cid, rid]);
  const [summary, setSummary] = useState<PayrollSummary | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const s = summary ?? load.data;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!s) return load.error ? <ErrorBox error={load.error} /> : <Loading rows={4} />;
  const { run, totals } = s;
  const draft = run.status === "draft";
  const blocking = s.warnings.some((w) => w.blocking);
  const label = `${MONTHS[run.month - 1]} ${run.year}`;

  return (
    <div className="stack">
      <Link to=".." relative="path" className="muted row" style={{ gap: 6 }}><ArrowLeft size={16} /> Lønn</Link>
      <PageHead eyebrow={`Utbetales ${formatDate(run.pay_date)}`} title={<>Lønn <em>{label}</em></>}
        action={<span className={`badge ${draft ? "honey" : "ok"}`}>{draft ? "Utkast" : "Bokført"}</span>} />

      <div className="tiles">
        <div className="tile wide">
          <div className="label">Til utbetaling (netto)</div>
          <div className="value"><Amount ore={totals.net_ore} /> <em>kr</em></div>
          <div className="label" style={{ marginTop: 8 }}>A-melding innen {formatDate(s.a_melding_due)}</div>
        </div>
        <div className="tile"><div className="label">Brutto</div><div className="value"><Amount ore={totals.gross_ore} /></div></div>
        <div className="tile"><div className="label">Skattetrekk</div><div className="value"><Amount ore={totals.tax_ore} /></div></div>
        <div className="tile">
          <div className="label">AGA ({(run.aga_rate_bp / 100).toLocaleString("nb-NO")} %)</div>
          <div className="value"><Amount ore={totals.aga_ore + totals.aga_holiday_ore} /></div>
        </div>
        <div className="tile"><div className="label">Feriepenger</div><div className="value"><Amount ore={totals.holiday_pay_ore} /></div></div>
      </div>

      {s.warnings.map((w) => <Notice key={w.code + w.message} kind="warn">{w.message}</Notice>)}
      <ErrorBox error={error} />

      <section className="card stack" style={{ padding: 0 }}>
        <div className="spread" style={{ padding: "16px 18px 0" }}><h2>Ansatte</h2></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Ansatt</th><th className="right">Brutto</th><th className="right">Netto</th></tr></thead>
            <tbody>
              {s.lines.map((ln) => (
                <LineRow key={ln.employee_id} ln={ln} draft={draft} editing={editing === ln.employee_id}
                  onEdit={() => setEditing(editing === ln.employee_id ? null : ln.employee_id)}
                  payslip={`/c/${cid}/lonn/${rid}/slipp/${ln.employee_id}`}
                  onSave={(change) => act(async () => {
                    setSummary(await api.updatePayrollLine(cid, rid, ln.employee_id, change));
                    setEditing(null);
                    setReviewing(false);
                  })} busy={busy} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {draft && !reviewing && (
        <div className="stack-sm">
          <button className="primary block" disabled={blocking || busy || !s.voucher_draft} onClick={() => setReviewing(true)}>
            <ShieldCheck size={18} /> Se over lønnsbilaget
          </button>
          <button className="ghost block danger" disabled={busy}
            onClick={() => act(async () => { await api.cancelPayrollRun(cid, rid); await load.reload(); setSummary(null); })}>
            <Trash2 size={16} /> Forkast utkastet
          </button>
        </div>
      )}

      {draft && reviewing && s.voucher_draft && (
        <section className="card stack">
          <h2>Lønnsbilag {label}</h2>
          <div className="table-wrap" style={{ padding: 0 }}>
            <table>
              <tbody>
                {s.voucher_draft.lines.map((l, i) => (
                  <tr key={i}>
                    <td><span className="acc-no">{l.account}</span>{l.description}</td>
                    <td className="right"><Amount ore={l.amount_ore} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Notice>Når du godkjenner, bokføres lønnen og kjøringen låses. Du er ansvarlig for at tallene stemmer.</Notice>
          <button className="primary block" disabled={busy} onClick={() => act(async () => {
            await api.approvePayrollRun(cid, rid, s.content_hash ?? "");
            setSummary(null);
            setReviewing(false);
            await load.reload();
          })}>
            <CheckCircle2 size={18} /> Godkjenn og bokfør
          </button>
          <button className="ghost block" onClick={() => setReviewing(false)}>Tilbake</button>
        </section>
      )}

      {!draft && (
        <section className="card stack">
          <h2>Neste steg</h2>
          <button className="primary block" disabled={busy} onClick={() => act(async () =>
            saveBlob(await api.payrollPaymentFile(cid, rid), `lonn-${run.year}-${String(run.month).padStart(2, "0")}.xml`))}>
            <Download size={18} /> Last ned betalingsfil
          </button>
          <Notice>
            Filen har nettolønn til hver ansatt og overføring av skattetrekket til skattetrekkskontoen. Last den opp i
            nettbanken og godkjenn med BankID. A-meldingen sendes fra Bokbuzz når tilgangen fra Skatteetaten er på
            plass; til da leverer du den i Altinn innen {formatDate(s.a_melding_due)}.
          </Notice>
          {run.voucher_id && <Link to={`/c/${cid}/bilag/${run.voucher_id}`}>Se bokført bilag</Link>}
        </section>
      )}
    </div>
  );
}

function LineRow({ ln, draft, editing, onEdit, onSave, payslip, busy }: {
  ln: PayrollLine; draft: boolean; editing: boolean; onEdit: () => void; payslip: string; busy: boolean;
  onSave: (c: { hours_x100: number | null; bonus_ore: number; tax_override_ore: number | null; note: string | null }) => void;
}) {
  const [hours, setHours] = useState(ln.hours_x100 != null ? String(ln.hours_x100 / 100).replace(".", ",") : "");
  const [bonus, setBonus] = useState(ln.bonus_ore ? formatOre(ln.bonus_ore) : "");
  const [tax, setTax] = useState(ln.tax_manual ? formatOre(ln.tax_ore) : "");
  const [err, setErr] = useState<string | null>(null);

  function save() {
    const h = hours.trim() ? parseKroner(hours) : null;
    const b = bonus.trim() ? parseKroner(bonus) : 0;
    const t = tax.trim() ? parseKroner(tax) : null;
    if ((hours.trim() && h == null) || b == null || (tax.trim() && t == null)) return setErr("Ugyldig tall");
    setErr(null);
    onSave({ hours_x100: h, bonus_ore: b, tax_override_ore: t, note: ln.note });
  }

  return (
    <>
      <tr>
        <td>
          <span className="acc-no">
            {ln.pay_type === "hourly" ? `${ln.hours_x100 != null ? (ln.hours_x100 / 100).toLocaleString("nb-NO") : "–"} t · ` : ""}
            trekk {formatOre(ln.tax_ore)}{ln.tax_manual ? " (manuelt)" : ""}
          </span>
          {ln.name}
          <div className="row" style={{ gap: 4, marginTop: 4 }}>
            {draft && <button className="ghost" style={{ minHeight: 30, padding: "2px 8px" }} onClick={onEdit}>
              <Pencil size={14} /> Endre</button>}
            <Link to={payslip} className="button ghost" style={{ minHeight: 30, padding: "2px 8px" }}>
              <FileText size={14} /> Slipp</Link>
          </div>
        </td>
        <td className="right"><Amount ore={ln.gross_ore} /></td>
        <td className="right"><Amount ore={ln.net_ore} /></td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={3}>
            <div className="row">
              {ln.pay_type === "hourly" && (
                <div style={{ flex: "1 1 90px" }}>
                  <label htmlFor={`h-${ln.employee_id}`}>Timer</label>
                  <input id={`h-${ln.employee_id}`} inputMode="decimal" value={hours} onChange={(e) => setHours(e.target.value)} />
                </div>
              )}
              <div style={{ flex: "1 1 110px" }}>
                <label htmlFor={`b-${ln.employee_id}`}>Tillegg kr</label>
                <input id={`b-${ln.employee_id}`} inputMode="decimal" value={bonus} onChange={(e) => setBonus(e.target.value)} />
              </div>
              <div style={{ flex: "1 1 110px" }}>
                <label htmlFor={`t-${ln.employee_id}`}>Trekk kr{ln.tax_card_kind === "table" ? ` (tabell ${ln.tax_table})` : ""}</label>
                <input id={`t-${ln.employee_id}`} inputMode="decimal" placeholder="auto" value={tax}
                  onChange={(e) => setTax(e.target.value)} />
              </div>
            </div>
            <ErrorBox error={err} />
            <button className="primary block" style={{ marginTop: 8 }} disabled={busy} onClick={save}>Oppdater</button>
          </td>
        </tr>
      )}
    </>
  );
}
