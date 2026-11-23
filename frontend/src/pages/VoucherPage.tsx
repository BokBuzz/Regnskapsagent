import { useState } from "react";
import { Link, useParams } from "react-router-dom";
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
      <Link to={`/c/${cid}/bilag`}>← Bokførte bilag</Link>
      <h1>
        Bilag {v.series}{v.number}/{v.year}
      </h1>
      <p>
        {formatDate(v.voucher_date)} · {v.description}
      </p>
      <div className="card table-wrap">
        <table>
          <thead>
            <tr><th>Konto</th><th>MVA</th><th className="right">Debet</th><th className="right">Kredit</th></tr>
          </thead>
          <tbody>
            {v.lines?.map((l) => (
              <tr key={l.line_no}>
                <td>{l.account} {names[l.account] ?? ""}</td>
                <td>{l.vat_code ?? ""}</td>
                <td className="right">{l.amount_ore > 0 && <Amount ore={l.amount_ore} />}</td>
                <td className="right">{l.amount_ore < 0 && <Amount ore={-l.amount_ore} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">Bokførte bilag kan ikke endres eller slettes. Feil rettes med et reverseringsbilag.</p>
      {done ? (
        <Notice kind="ok">{done}</Notice>
      ) : v.reverses_voucher_id ? null : !reversing ? (
        <button onClick={() => setReversing(true)}>Reverser bilaget</button>
      ) : (
        <div className="card stack">
          <label htmlFor="reason">Begrunnelse for reversering</label>
          <input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          <ErrorBox error={error} />
          <button className="danger" disabled={reason.trim().length < 3} onClick={() => void reverse()}>
            Bekreft reversering
          </button>
        </div>
      )}
    </div>
  );
}
