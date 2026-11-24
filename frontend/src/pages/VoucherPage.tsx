import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Lock, ShieldCheck, Undo2 } from "lucide-react";
import { Amount, ErrorBox, Loading, Notice } from "../components/ui";
import { useAuth } from "../lib/auth";
import { formatDate } from "../lib/money";
import { useLoad } from "../lib/useLoad";

export default function VoucherPage() {
  const { cid = "", vid = "" } = useParams();
  const { api } = useAuth();
  const voucher = useLoad(() => api.voucher(cid, vid), [api, cid, vid]);
  const accounts = useLoad(() => api.accounts(cid), [api, cid]);
  const [reversing, setReversing] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (voucher.loading) return <Loading />;
  const v = voucher.data;
  if (!v) return <ErrorBox error={voucher.error ?? "Fant ikke bilaget"} />;
  const names = Object.fromEntries((accounts.data ?? []).map((a) => [a.number, a.name]));
  const total = (v.lines ?? []).reduce((s, l) => s + (l.amount_ore > 0 ? l.amount_ore : 0), 0);

  async function reverse() {
    setError(null);
    try {
      const r = await api.reverse(cid, vid, reason);
      setDone(`Reversert med bilag ${r.series}${r.number}/${r.year}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="stack">
      <Link className="back" to={`/c/${cid}/bilag`}><ArrowLeft size={18} /> Bokførte bilag</Link>
      <section className="card receipt stack">
        <div className="head">
          <span className="stamp"><ShieldCheck size={26} /></span>
          <div className="grow">
            <div className="muted small mono">{formatDate(v.voucher_date)}</div>
            <h1 style={{ fontSize: "1.4rem" }}>Bilag {v.series}{v.number}/{v.year}</h1>
          </div>
          <span className="num" style={{ fontSize: "1.05rem" }}><Amount ore={total} /></span>
        </div>
        <p className="lede" style={{ color: "var(--text)" }}>{v.description}</p>
        <div className="card tinted table-wrap" style={{ padding: "4px 10px" }}>
          <table>
            <thead>
              <tr><th>Konto</th><th className="right">Debet</th><th className="right">Kredit</th></tr>
            </thead>
            <tbody>
              {v.lines?.map((l) => (
                <tr key={l.line_no}>
                  <td>
                    <span className="acc-no">{l.account}{l.vat_code ? ` · MVA-kode ${l.vat_code}` : ""}</span>
                    {names[l.account] ?? ""}
                  </td>
                  <td className="right">{l.amount_ore > 0 && <Amount ore={l.amount_ore} />}</td>
                  <td className="right">{l.amount_ore < 0 && <Amount ore={-l.amount_ore} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small row mono" style={{ gap: 6, flexWrap: "nowrap", alignItems: "flex-start" }}>
          <Lock size={15} style={{ flex: "none", marginTop: 3 }} />
          Bokførte bilag kan ikke endres eller slettes. Feil rettes med et reverseringsbilag.
        </p>
      </section>
      {done ? (
        <Notice kind="ok">{done}</Notice>
      ) : v.reverses_voucher_id ? null : !reversing ? (
        <button className="block" onClick={() => setReversing(true)}><Undo2 size={18} /> Reverser bilaget</button>
      ) : (
        <div className="card stack">
          <label htmlFor="reason">Begrunnelse for reversering</label>
          <input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          <ErrorBox error={error} />
          <button className="danger solid block" disabled={reason.trim().length < 3} onClick={() => void reverse()}>
            Bekreft reversering
          </button>
        </div>
      )}
    </div>
  );
}
