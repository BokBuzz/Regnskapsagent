import { useState } from "react";
import { useParams } from "react-router-dom";
import { Download, Receipt, Send } from "lucide-react";
import { Amount, ErrorBox, Loading, Notice, PageHead, YearSelect } from "../components/ui";
import { useAuth } from "../lib/auth";
import { formatDate } from "../lib/money";
import { useLoad } from "../lib/useLoad";

const TERMS = ["Jan–feb", "Mar–apr", "Mai–jun", "Jul–aug", "Sep–okt", "Nov–des"];

function currentTerm(): number {
  // Forrige avsluttede termin er den som normalt skal sendes nå.
  const m = new Date().getMonth(); // 0–11
  const t = Math.floor(m / 2); // 0–5, inneværende termin
  return t === 0 ? 6 : t;
}

/**
 * MVA-melding: utkast beregnet fra hovedboken, kontroller før innsending og nedlasting.
 * Innsending til Skatteetaten kobles på når Bokbuzz har fått tilgang (ID-porten).
 */
export default function VatPage() {
  const { cid = "" } = useParams();
  const { api } = useAuth();
  const company = useLoad(() => api.company(cid), [api, cid]);
  const annual = company.data?.vat_term === "annual";
  const [year, setYear] = useState(() => (currentTerm() === 6 && new Date().getMonth() < 2
    ? new Date().getFullYear() - 1 : new Date().getFullYear()));
  const [term, setTerm] = useState(currentTerm());
  const t = annual ? 1 : term;
  const draft = useLoad(() => api.vatReturn(cid, year, t), [api, cid, year, t]);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setError(null);
    try {
      const blob = await api.vatReturnXml(cid, year, t);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `mva-${year}-${t}.xml`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const d = draft.data;
  const blocking = d?.checks.some((c) => c.severity === "error") ?? false;
  return (
    <div className="stack">
      <PageHead eyebrow="Merverdiavgift" title={<>MVA-<em>melding</em></>}
        action={<YearSelect year={year} onChange={setYear} />} />

      {!annual && (
        <div className="row" role="tablist" aria-label="Termin">
          {TERMS.map((label, i) => (
            <button key={label} role="tab" aria-selected={term === i + 1}
              className={term === i + 1 ? "primary" : "ghost"} style={{ minHeight: 38, padding: "6px 12px" }}
              onClick={() => setTerm(i + 1)}>{label}</button>
          ))}
        </div>
      )}

      <ErrorBox error={error ?? draft.error ?? company.error} />
      {draft.loading || !d ? (
        draft.error ? null : <Loading rows={3} />
      ) : (
        <>
          <div className="tiles">
            <div className="tile wide">
              <div className="label"><Receipt size={14} /> {d.label} · frist {formatDate(d.due)}</div>
              <div className="value">
                <Amount ore={Math.abs(d.total_ore)} /> <em>kr</em>
              </div>
              <div className="label" style={{ marginTop: 8 }}>
                {d.result === "to_pay" ? "Å betale" : d.result === "refund" ? "Til gode" : "Ingenting å betale"}
              </div>
            </div>
          </div>

          {d.checks.map((c) => (
            <Notice key={c.code} kind={c.severity === "info" ? "info" : "warn"}>{c.message}</Notice>
          ))}

          <section className="card stack" style={{ padding: 0 }}>
            <div className="spread" style={{ padding: "16px 18px 0" }}>
              <h2>Spesifikasjon</h2>
              <span className="badge neutral">{formatDate(d.from)}–{formatDate(d.to)}</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Kode</th><th className="right">Grunnlag</th><th className="right">MVA</th></tr>
                </thead>
                <tbody>
                  {d.lines.length === 0 && (
                    <tr><td colSpan={3} className="muted">Ingen MVA-posteringer i terminen.</td></tr>
                  )}
                  {d.lines.map((ln) => (
                    <tr key={ln.code}>
                      <td><span className="acc-no">{ln.code}</span>{ln.description}
                        {ln.rate_bp != null && ln.rate_bp > 0 ? ` (${ln.rate_bp / 100} %)` : ""}</td>
                      <td className="right">{ln.direction === "output" ? <Amount ore={ln.base_ore} /> : "–"}</td>
                      <td className="right"><Amount ore={ln.vat_ore} /></td>
                    </tr>
                  ))}
                  <tr className="total">
                    <td>Sum</td><td />
                    <td className="right"><Amount ore={d.total_ore} /></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <div className="stack-sm">
            <button className="block" onClick={() => void download()}>
              <Download size={18} /> Last ned utkast (XML)
            </button>
            <button className="primary block" disabled={!d.submission_available || blocking}>
              <Send size={18} /> Send til Skatteetaten
            </button>
            {!d.submission_available && (
              <Notice>
                Innsending direkte fra Bokbuzz kommer når tilgangen fra Skatteetaten er på plass. Til da kan du
                bruke tallene over i MVA-meldingen i Altinn. Du sender alltid selv, og ingenting sendes uten at du
                bekrefter.
              </Notice>
            )}
          </div>
        </>
      )}
    </div>
  );
}
