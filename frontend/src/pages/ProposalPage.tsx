import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Amount, ErrorBox, Loading, Notice } from "../components/ui";
import type { Account, Proposal, VatCode, Voucher } from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  paymentAccounts,
  draftFromForm,
  formErrors,
  formFromDraft,
  formTotal,
  lineVat,
  type FormLine,
  type VoucherForm,
} from "../lib/draft";
import { formatOre, parseKroner } from "../lib/money";
import { useLoad } from "../lib/useLoad";

/**
 * Kontroll og bokføring av ett bilag.
 * Klikk 1: å åpne siden starter en gjennomgang (originalen vises ved siden av forslaget).
 * Klikk 2: kunden bekrefter at bilaget er kontrollert og trykker «Bokfør».
 */
export default function ProposalPage() {
  const { cid = "", pid = "" } = useParams();
  const { api } = useAuth();
  const proposal = useLoad(() => api.proposal(cid, pid), [api, cid, pid]);
  const accounts = useLoad(() => api.accounts(cid), [api, cid]);
  const vat = useLoad(() => api.vatCodes(), [api]);
  const company = useLoad(() => api.company(cid), [api, cid]);

  if (proposal.loading || accounts.loading || vat.loading || company.loading) return <Loading />;
  if (proposal.error || !proposal.data) return <ErrorBox error={proposal.error ?? "Fant ikke bilaget"} />;
  return <Review cid={cid} proposal={proposal.data} accounts={accounts.data ?? []} vatCodes={vat.data ?? []}
    orgForm={company.data?.org_form ?? "ENK"} />;
}

function Review({ cid, proposal, accounts, vatCodes, orgForm }: {
  cid: string;
  proposal: Proposal;
  accounts: Account[];
  vatCodes: VatCode[];
  orgForm: string;
}) {
  const { api } = useAuth();
  const open = proposal.status === "pending" || proposal.status === "needs_manual";
  const [token, setToken] = useState<string | null>(null);
  const [form, setForm] = useState<VoucherForm>(() => formFromDraft(proposal.draft));
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [posted, setPosted] = useState<Voucher | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [rejected, setRejected] = useState(false);

  // Klikk 1: gjennomgangen registreres når kunden åpner bilaget.
  useEffect(() => {
    if (!open) return;
    api.openReview(cid, proposal.id).then((r) => setToken(r.review_token), (e) => setError(e.message));
  }, [api, cid, proposal.id, open]);

  const rates = useMemo(() => Object.fromEntries(vatCodes.map((v) => [v.code, v.rate_bp])), [vatCodes]);
  const purchaseCodes = vatCodes.filter((v) => v.direction !== "output");
  const purchaseAccounts = accounts.filter((a) => a.account_type === "expense" || a.account_type === "asset");
  const total = formTotal(form, rates);
  const problems = formErrors(form);
  const payOptions = paymentAccounts(orgForm);
  if (!payOptions.some((p) => p.number === form.paymentAccount)) {
    const acc = accounts.find((a) => a.number === form.paymentAccount);
    payOptions.push({ number: form.paymentAccount, label: `${form.paymentAccount} ${acc?.name ?? ""}`.trim() });
  }

  function setLine(i: number, patch: Partial<FormLine>) {
    setForm((f) => ({ ...f, lines: f.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
    setChecked(false);
  }

  async function post() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      // Uendret forslag sendes ikke på nytt; da bokføres nøyaktig det KI-en foreslo.
      const current = draftFromForm(form, rates);
      const unchanged = JSON.stringify(current) === JSON.stringify(draftFromForm(formFromDraft(proposal.draft), rates));
      setPosted(await api.approve(cid, proposal.id, token, unchanged && proposal.draft ? undefined : current));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    setBusy(true);
    try {
      await api.reject(cid, proposal.id, reason);
      setRejected(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (posted) {
    return (
      <div className="stack">
        <Notice kind="ok">
          Bokført som bilag <strong>{posted.series}{posted.number}/{posted.year}</strong>.
        </Notice>
        <div className="row">
          <Link className="button primary" to={`/c/${cid}/innboks`}>Neste bilag</Link>
          <Link className="button" to={`/c/${cid}/bilag/${posted.id}`}>Se bilaget</Link>
        </div>
      </div>
    );
  }
  if (rejected) {
    return (
      <div className="stack">
        <Notice>Bilaget er avvist og blir ikke bokført.</Notice>
        <Link className="button" to={`/c/${cid}/innboks`}>Tilbake</Link>
      </div>
    );
  }

  return (
    <div className="stack">
      <Link to={`/c/${cid}/innboks`}>← Til kontroll</Link>
      <div className="review">
        <section className="original card">
          <h2 style={{ marginTop: 0 }}>Originalbilag</h2>
          <Original cid={cid} documentId={proposal.document_id} mime={proposal.document?.mime_type ?? ""} />
        </section>

        <section className="card stack">
          <div className="spread">
            <h2 style={{ margin: 0 }}>Forslag</h2>
            <span className="badge">Foreslått av KI{proposal.escalated ? " (kontrollert to ganger)" : ""}</span>
          </div>
          {!open && <Notice>Dette bilaget er allerede behandlet.</Notice>}
          {proposal.validation_errors.map((f) => (
            <Notice key={f.code} kind="warn">{f.message}</Notice>
          ))}
          {proposal.warnings.map((f) => (
            <Notice key={f.code} kind="warn">{f.message}</Notice>
          ))}
          {proposal.extraction?.supplier_name && (
            <p className="muted">
              Leverandør: {proposal.extraction.supplier_name}
              {proposal.extraction.supplier_orgnr ? ` (org.nr. ${proposal.extraction.supplier_orgnr})` : ""}
            </p>
          )}

          <div className="row" style={{ alignItems: "flex-end" }}>
            <div style={{ flex: "1 1 150px" }}>
              <label htmlFor="date">Bilagsdato</label>
              <input id="date" type="date" value={form.date} disabled={!open}
                onChange={(e) => { setForm({ ...form, date: e.target.value }); setChecked(false); }} />
            </div>
            <div style={{ flex: "2 1 220px" }}>
              <label htmlFor="desc">Beskrivelse</label>
              <input id="desc" value={form.description} disabled={!open}
                onChange={(e) => { setForm({ ...form, description: e.target.value }); setChecked(false); }} />
            </div>
          </div>

          {form.lines.map((l, i) => (
            <fieldset key={i} className="card stack" style={{ padding: 12 }} disabled={!open}>
              <legend className="muted">Linje {i + 1}</legend>
              <div>
                <label htmlFor={`acc${i}`}>Konto</label>
                <select id={`acc${i}`} value={l.account}
                  onChange={(e) => {
                    const acc = purchaseAccounts.find((a) => a.number === e.target.value);
                    setLine(i, { account: e.target.value, vatCode: acc?.default_vat_code ?? l.vatCode, vatOre: null });
                  }}>
                  <option value="">Velg konto</option>
                  {purchaseAccounts.map((a) => (
                    <option key={a.number} value={a.number}>{a.number} {a.name}</option>
                  ))}
                </select>
              </div>
              <div className="row">
                <div style={{ flex: "1 1 120px" }}>
                  <label htmlFor={`amt${i}`}>Beløp uten MVA</label>
                  <MoneyInput id={`amt${i}`} ore={l.netOre} onChange={(v) => setLine(i, { netOre: v, vatOre: null })} />
                </div>
                <div style={{ flex: "2 1 180px" }}>
                  <label htmlFor={`vat${i}`}>MVA</label>
                  <select id={`vat${i}`} value={l.vatCode} onChange={(e) => setLine(i, { vatCode: e.target.value, vatOre: null })}>
                    {purchaseCodes.map((v) => (
                      <option key={v.code} value={v.code}>{v.rate_bp / 100} % – {v.description}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="spread muted">
                <span>MVA: <Amount ore={lineVat(l, rates)} /></span>
                {form.lines.length > 1 && (
                  <button type="button" className="danger"
                    onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}>
                    Fjern linje
                  </button>
                )}
              </div>
            </fieldset>
          ))}
          {open && (
            <button type="button" onClick={() =>
              setForm({ ...form, lines: [...form.lines, { account: "", description: "", netOre: null, vatCode: "1", vatOre: null }] })}>
              Legg til linje (annen MVA-sats)
            </button>
          )}

          <div>
            <label htmlFor="pay">Betalt fra</label>
            <select id="pay" value={form.paymentAccount} disabled={!open}
              onChange={(e) => { setForm({ ...form, paymentAccount: e.target.value }); setChecked(false); }}>
              {payOptions.map((p) => (
                <option key={p.number} value={p.number}>{p.label}</option>
              ))}
            </select>
          </div>

          <div className="spread" style={{ fontSize: "1.1rem" }}>
            <strong>Totalt inkl. MVA</strong>
            <strong><Amount ore={total} /></strong>
          </div>
          {proposal.extraction?.total_amount_ore != null && proposal.extraction.total_amount_ore !== total && (
            <Notice kind="warn">
              Totalen på kvitteringen var {formatOre(proposal.extraction.total_amount_ore)} kr.
            </Notice>
          )}

          {open && (
            <>
              {problems.length > 0 && <Notice kind="warn">{problems.join(" ")}</Notice>}
              <label className="check">
                <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)}
                  disabled={problems.length > 0} />
                <span>Jeg har kontrollert bilaget mot originalen, og vil bokføre det.</span>
              </label>
              <ErrorBox error={error} />
              <button className="primary" disabled={!checked || busy || !token || problems.length > 0}
                onClick={() => void post()}>
                Bokfør
              </button>
              {!rejecting ? (
                <button type="button" onClick={() => setRejecting(true)}>Ikke bokfør dette bilaget</button>
              ) : (
                <div className="stack">
                  <label htmlFor="reason">Hvorfor? (for eksempel privat kjøp eller duplikat)</label>
                  <input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} />
                  <button className="danger" disabled={busy || reason.trim().length < 3} onClick={() => void reject()}>
                    Avvis bilaget
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function MoneyInput({ id, ore, onChange }: { id: string; ore: number | null; onChange: (v: number | null) => void }) {
  const [text, setText] = useState(ore === null ? "" : formatOre(ore));
  const [bad, setBad] = useState(false);
  return (
    <input id={id} inputMode="decimal" value={text} aria-invalid={bad}
      onChange={(e) => {
        setText(e.target.value);
        const v = parseKroner(e.target.value);
        setBad(e.target.value.trim() !== "" && v === null);
        onChange(v);
      }} />
  );
}

function Original({ cid, documentId, mime }: { cid: string; documentId: string; mime: string }) {
  const { api } = useAuth();
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let objectUrl: string | null = null;
    api.documentBlob(cid, documentId).then(
      (blob) => {
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      },
      (e) => setError(e.message),
    );
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [api, cid, documentId]);
  if (error) return <ErrorBox error={error} />;
  if (!url) return <Loading />;
  if (mime === "application/pdf") return <object data={url} type="application/pdf" aria-label="Originalbilag (PDF)" />;
  if (mime === "image/heic")
    return <p><a href={url} download>Last ned originalen</a> (HEIC kan ikke vises i alle nettlesere).</p>;
  return <img src={url} alt="Originalbilag" />;
}
