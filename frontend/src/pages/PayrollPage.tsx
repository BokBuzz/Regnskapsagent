import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Download, Plus, Settings, UserPlus, Users, Wallet } from "lucide-react";
import { Amount, EmptyState, ErrorBox, Loading, Notice, PageHead } from "../components/ui";
import type { Api, NewEmployee, PayrollSettings } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDate, formatOre, parseKroner } from "../lib/money";
import { useLoad } from "../lib/useLoad";

export const MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september",
  "oktober", "november", "desember"];
const ZONES = ["1", "1a", "2", "3", "4", "4a", "5"];
const TERMS = ["Jan–feb", "Mar–apr", "Mai–jun", "Jul–aug", "Sep–okt", "Nov–des"];

export async function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

const digits = (s: string) => s.replace(/\D/g, "");
const orNull = (s: string) => (digits(s) ? digits(s) : null);

/**
 * Lønn: innstillinger, ansatte, lønnskjøringer og terminbetalinger (skattetrekk og arbeidsgiveravgift).
 * Kunden kjører lønnen selv og godkjenner hvert steg.
 */
export default function PayrollPage() {
  const { cid = "" } = useParams();
  const { api } = useAuth();
  const settings = useLoad(() => api.payrollSettings(cid), [api, cid]);
  const employees = useLoad(() => api.employees(cid), [api, cid]);
  const runs = useLoad(() => api.payrollRuns(cid), [api, cid]);
  const [editSettings, setEditSettings] = useState(false);
  const [addEmployee, setAddEmployee] = useState(false);

  if (settings.loading && !settings.data) return <Loading rows={4} />;
  const hasSettings = !!settings.data;
  return (
    <div className="stack">
      <PageHead eyebrow="Lønn" title={<>Lønns<em>kjøring</em></>} />
      <ErrorBox error={settings.error ?? employees.error ?? runs.error} />

      {!hasSettings || editSettings ? (
        <SettingsForm api={api} cid={cid} initial={settings.data}
          onSaved={() => { setEditSettings(false); void settings.reload(); }}
          onCancel={hasSettings ? () => setEditSettings(false) : undefined} />
      ) : (
        <>
          <NewRun api={api} cid={cid} disabled={!employees.data?.length} />

          <section className="card stack" style={{ padding: 0 }}>
            <div className="spread" style={{ padding: "16px 18px 0" }}>
              <h2>Kjøringer</h2>
            </div>
            <div className="table-wrap">
              <table>
                <tbody>
                  {runs.data?.length === 0 && <tr><td className="muted">Ingen lønnskjøringer ennå.</td></tr>}
                  {runs.data?.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <Link to={r.id}><span className="acc-no">utbetales {formatDate(r.pay_date)}</span>
                          Lønn {MONTHS[r.month - 1]} {r.year}</Link>
                      </td>
                      <td className="right">
                        <span className={`badge ${r.status === "approved" ? "ok" : "honey"}`}>
                          {r.status === "approved" ? "Bokført" : "Utkast"}</span>
                        <div><Amount ore={r.gross_ore ?? 0} /></div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card stack">
            <div className="spread">
              <h2><Users size={18} /> Ansatte</h2>
              <button className="ghost" onClick={() => setAddEmployee((v) => !v)}><UserPlus size={18} /> Ny</button>
            </div>
            {addEmployee && (
              <EmployeeForm api={api} cid={cid} onSaved={() => { setAddEmployee(false); void employees.reload(); }} />
            )}
            {employees.data?.length === 0 && !addEmployee && (
              <EmptyState icon={<Users size={22} />} title="Ingen ansatte ennå">
                Legg inn den første ansatte for å kjøre lønn.
              </EmptyState>
            )}
            {employees.data?.map((e) => (
              <div key={e.id} className="spread">
                <span>{e.name}<span className="acc-no">
                  {e.pay_type === "monthly" ? `${formatOre(e.monthly_salary_ore ?? 0)} kr/mnd`
                    : `${formatOre(e.hourly_rate_ore ?? 0)} kr/time`} ·{" "}
                  {e.tax_card_kind === "percent" ? `${e.tax_percent} % trekk`
                    : e.tax_card_kind === "table" ? `tabell ${e.tax_table}` : "frikort"}
                </span></span>
                <span className="badge neutral">{e.end_date ? `slutt ${formatDate(e.end_date)}` : "aktiv"}</span>
              </div>
            ))}
          </section>

          <TermSection api={api} cid={cid} settings={settings.data!} />

          <button className="ghost block" onClick={() => setEditSettings(true)}>
            <Settings size={18} /> Lønnsinnstillinger
          </button>
        </>
      )}
    </div>
  );
}

function NewRun({ api, cid, disabled }: { api: Api; cid: string; disabled: boolean }) {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [payDate, setPayDate] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-20`);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function create(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await api.createPayrollRun(cid, year, month, payDate);
      navigate(`/c/${cid}/lonn/${s.run.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={(e) => void create(e)}>
      <h2><Wallet size={18} /> Ny lønnskjøring</h2>
      <div className="row">
        <div style={{ flex: "1 1 140px" }}>
          <label htmlFor="run-month">Måned</label>
          <select id="run-month" value={month} onChange={(e) => setMonth(Number(e.target.value))}>
            {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select>
        </div>
        <div style={{ flex: "1 1 90px" }}>
          <label htmlFor="run-year">År</label>
          <input id="run-year" type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} />
        </div>
        <div style={{ flex: "1 1 150px" }}>
          <label htmlFor="run-date">Utbetales</label>
          <input id="run-date" type="date" required value={payDate} onChange={(e) => setPayDate(e.target.value)} />
        </div>
      </div>
      <ErrorBox error={error} />
      <button className="primary block" disabled={disabled || busy}><Plus size={18} /> Lag utkast</button>
      {disabled && <Notice>Legg inn minst én ansatt først.</Notice>}
    </form>
  );
}

function SettingsForm({ api, cid, initial, onSaved, onCancel }: {
  api: Api; cid: string; initial: PayrollSettings | null; onSaved: () => void; onCancel?: () => void;
}) {
  const [s, setS] = useState<Record<string, string>>({
    aga_zone: initial?.aga_zone ?? "1",
    holiday_rate_bp: String(initial?.holiday_rate_bp ?? 1020),
    pay_from_account: initial?.pay_from_account ?? "",
    tax_withholding_account: initial?.tax_withholding_account ?? "",
    kid_withholding: initial?.kid_withholding ?? "",
    kid_aga: initial?.kid_aga ?? "",
    tax_authority_account: initial?.tax_authority_account ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const set = (k: string) => (e: { target: { value: string } }) => setS({ ...s, [k]: e.target.value });

  async function save(ev: FormEvent) {
    ev.preventDefault();
    setError(null);
    try {
      await api.savePayrollSettings(cid, {
        aga_zone: s.aga_zone, holiday_rate_bp: Number(s.holiday_rate_bp), pay_from_account: digits(s.pay_from_account),
        tax_withholding_account: orNull(s.tax_withholding_account), kid_withholding: orNull(s.kid_withholding),
        kid_aga: orNull(s.kid_aga), tax_authority_account: orNull(s.tax_authority_account),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const field = (k: string, label: string, hint?: string) => (
    <div>
      <label htmlFor={`ps-${k}`}>{label}</label>
      <input id={`ps-${k}`} inputMode="numeric" value={s[k]} onChange={set(k)} placeholder={hint} />
    </div>
  );
  return (
    <form className="card stack" onSubmit={(e) => void save(e)}>
      <h2><Settings size={18} /> Lønnsinnstillinger</h2>
      {!initial && <Notice>Før første lønnskjøring trenger Bokbuzz kontoene lønnen betales fra og til.</Notice>}
      <div className="row">
        <div style={{ flex: "1 1 120px" }}>
          <label htmlFor="ps-zone">AGA-sone</label>
          <select id="ps-zone" value={s.aga_zone} onChange={set("aga_zone")}>
            {ZONES.map((z) => <option key={z} value={z}>Sone {z}</option>)}
          </select>
        </div>
        <div style={{ flex: "1 1 160px" }}>
          <label htmlFor="ps-holiday">Feriepenger</label>
          <select id="ps-holiday" value={s.holiday_rate_bp} onChange={set("holiday_rate_bp")}>
            <option value="1020">10,2 % (4 uker + 1 dag)</option>
            <option value="1200">12 % (5 uker)</option>
          </select>
        </div>
      </div>
      {field("pay_from_account", "Lønn betales fra (driftskonto)", "11 siffer")}
      {field("tax_withholding_account", "Skattetrekkskonto", "11 siffer")}
      {field("tax_authority_account", "Skatteetatens kontonummer", "fra skatteetaten.no")}
      {field("kid_withholding", "KID for forskuddstrekk")}
      {field("kid_aga", "KID for arbeidsgiveravgift")}
      <ErrorBox error={error} />
      <div className="row">
        <button className="primary" style={{ flex: 1 }}>Lagre</button>
        {onCancel && <button type="button" className="ghost" onClick={onCancel}>Avbryt</button>}
      </div>
    </form>
  );
}

function EmployeeForm({ api, cid, onSaved }: { api: Api; cid: string; onSaved: () => void }) {
  const [f, setF] = useState<Record<string, string>>({
    name: "", national_id: "", bank_account: "", email: "", pay_type: "monthly", amount: "",
    tax_card_kind: "percent", tax_percent: "", tax_table: "", start_date: new Date().toISOString().slice(0, 10),
  });
  const [error, setError] = useState<string | null>(null);
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function save(ev: FormEvent) {
    ev.preventDefault();
    setError(null);
    const amount = parseKroner(f.amount);
    if (amount == null || amount <= 0) return setError("Skriv inn lønn eller timesats i kroner");
    const e: NewEmployee = {
      name: f.name.trim(), national_id: digits(f.national_id), bank_account: digits(f.bank_account),
      email: f.email.trim() || null, position_pct_bp: 10000, pay_type: f.pay_type as "monthly" | "hourly",
      monthly_salary_ore: f.pay_type === "monthly" ? amount : null,
      hourly_rate_ore: f.pay_type === "hourly" ? amount : null,
      tax_card_kind: f.tax_card_kind as "percent" | "table" | "none",
      tax_percent: f.tax_card_kind === "percent" ? Number(f.tax_percent) : null,
      tax_table: f.tax_card_kind === "table" ? f.tax_table : null,
      start_date: f.start_date, end_date: null,
    };
    try {
      await api.createEmployee(cid, e);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <form className="card tinted stack" onSubmit={(e) => void save(e)}>
      <div><label htmlFor="em-name">Navn</label><input id="em-name" required value={f.name} onChange={set("name")} /></div>
      <div className="row">
        <div style={{ flex: "1 1 160px" }}>
          <label htmlFor="em-nid">Fødselsnummer</label>
          <input id="em-nid" inputMode="numeric" required value={f.national_id} onChange={set("national_id")} />
        </div>
        <div style={{ flex: "1 1 160px" }}>
          <label htmlFor="em-acc">Kontonummer</label>
          <input id="em-acc" inputMode="numeric" required value={f.bank_account} onChange={set("bank_account")} />
        </div>
      </div>
      <div className="row">
        <div style={{ flex: "1 1 140px" }}>
          <label htmlFor="em-type">Lønnstype</label>
          <select id="em-type" value={f.pay_type} onChange={set("pay_type")}>
            <option value="monthly">Fastlønn</option>
            <option value="hourly">Timelønn</option>
          </select>
        </div>
        <div style={{ flex: "1 1 140px" }}>
          <label htmlFor="em-amount">{f.pay_type === "monthly" ? "Kr per måned" : "Kr per time"}</label>
          <input id="em-amount" inputMode="decimal" required value={f.amount} onChange={set("amount")} />
        </div>
      </div>
      <div className="row">
        <div style={{ flex: "1 1 140px" }}>
          <label htmlFor="em-card">Skattekort</label>
          <select id="em-card" value={f.tax_card_kind} onChange={set("tax_card_kind")}>
            <option value="percent">Prosentkort</option>
            <option value="table">Tabellkort</option>
            <option value="none">Frikort</option>
          </select>
        </div>
        {f.tax_card_kind === "percent" && (
          <div style={{ flex: "1 1 100px" }}>
            <label htmlFor="em-pct">Prosent</label>
            <input id="em-pct" inputMode="numeric" required value={f.tax_percent} onChange={set("tax_percent")} />
          </div>
        )}
        {f.tax_card_kind === "table" && (
          <div style={{ flex: "1 1 100px" }}>
            <label htmlFor="em-table">Tabell</label>
            <input id="em-table" inputMode="numeric" required value={f.tax_table} onChange={set("tax_table")} />
          </div>
        )}
      </div>
      <div><label htmlFor="em-start">Startdato</label>
        <input id="em-start" type="date" required value={f.start_date} onChange={set("start_date")} /></div>
      <ErrorBox error={error} />
      <button className="primary block"><UserPlus size={18} /> Legg til ansatt</button>
    </form>
  );
}

function TermSection({ api, cid, settings }: { api: Api; cid: string; settings: PayrollSettings }) {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [term, setTerm] = useState(Math.floor(now.getMonth() / 2) + 1);
  const t = useLoad(() => api.termPayments(cid, year, term), [api, cid, year, term]);
  const [error, setError] = useState<string | null>(null);

  async function download(kind: "withholding" | "aga") {
    setError(null);
    try {
      await saveBlob(await api.termPaymentFile(cid, year, term, kind), `${kind === "aga" ? "aga" : "skattetrekk"}-${year}-${term}.xml`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section className="card stack">
      <div className="spread">
        <h2>Skatt og avgift</h2>
        <select aria-label="År" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: "auto" }}>
          {[now.getFullYear() - 1, now.getFullYear()].map((y) => <option key={y}>{y}</option>)}
        </select>
      </div>
      <div className="row" role="tablist" aria-label="Termin">
        {TERMS.map((label, i) => (
          <button key={label} role="tab" aria-selected={term === i + 1} className={term === i + 1 ? "primary" : "ghost"}
            style={{ minHeight: 34, padding: "4px 10px" }} onClick={() => setTerm(i + 1)}>{label}</button>
        ))}
      </div>
      <ErrorBox error={error ?? t.error} />
      {t.data && (
        <>
          <div className="spread"><span>Forskuddstrekk</span><Amount ore={t.data.withholding_ore} /></div>
          <div className="spread"><span>Arbeidsgiveravgift</span><Amount ore={t.data.aga_ore} /></div>
          <div className="spread muted"><span>Forfall</span><span>{formatDate(t.data.due)}</span></div>
          {t.data.missing.length > 0 ? (
            <Notice kind="warn">Legg inn KID-numrene og Skatteetatens kontonummer i lønnsinnstillingene for å lage
              betalingsfil.</Notice>
          ) : (
            <div className="row">
              <button style={{ flex: 1 }} disabled={!t.data.withholding_ore} onClick={() => void download("withholding")}>
                <Download size={16} /> Skattetrekk</button>
              <button style={{ flex: 1 }} disabled={!t.data.aga_ore} onClick={() => void download("aga")}>
                <Download size={16} /> AGA</button>
            </div>
          )}
          {!settings.tax_withholding_account && (
            <Notice kind="warn">Skattetrekket skal stå på egen skattetrekkskonto (eller være sikret med bankgaranti).</Notice>
          )}
          <p className="muted" style={{ fontSize: "0.85rem" }}>
            Filene lastes opp i nettbanken. Du godkjenner betalingen der med BankID; Bokbuzz flytter aldri penger.
          </p>
        </>
      )}
    </section>
  );
}
