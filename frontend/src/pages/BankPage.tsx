import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle2, ChevronRight, FileUp, Landmark, RefreshCw, Sparkles, X } from "lucide-react";
import { Amount, EmptyState, ErrorBox, Loading, Notice, PageHead } from "../components/ui";
import type { BankTransaction } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDate } from "../lib/money";
import { useLoad } from "../lib/useLoad";

type Filter = "open" | "all" | "matched";

const STATUS: Record<NonNullable<BankTransaction["status"]>, { label: string; tone: string }> = {
  matched: { label: "Avstemt", tone: "ok" },
  suggested: { label: "Forslag til kobling", tone: "honey" },
  proposed: { label: "Bilag foreslått", tone: "honey" },
  missing_document: { label: "Mangler bilag", tone: "warn" },
};

/**
 * Bank: importer kontoutskrift (CAMT.053) og avstem.
 * Bokbuzz foreslår koblinger mellom banklinjer og bokførte bilag; kunden bekrefter.
 * Avstemming endrer aldri regnskapet.
 */
export default function BankPage() {
  const { cid = "" } = useParams();
  const { api } = useAuth();
  const [filter, setFilter] = useState<Filter>("open");
  const recon = useLoad(() => api.bankReconciliation(cid), [api, cid]);
  const txs = useLoad(() => api.bankTransactions(cid), [api, cid]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const reload = () => { void recon.reload(); void txs.reload(); };

  async function importFile(file: File) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { statements } = await api.importBankStatement(cid, file);
      const added = statements.reduce((s, st) => s + (st.duplicate ? 0 : st.new_count), 0);
      const bad = statements.some((st) => st.balance_ok === false);
      setNotice(statements.every((st) => st.duplicate)
        ? "Denne kontoutskriften er allerede importert."
        : `${added} nye banklinjer importert. Bokbuzz avstemmer dem nå; trykk oppdater om litt.`
          + (bad ? " Merk: inngående saldo pluss posteringene stemmer ikke med utgående saldo i filen." : ""));
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function decide(matchId: string, accept: boolean) {
    setError(null);
    try {
      await api.decideMatch(cid, matchId, accept);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const all = txs.data ?? [];
  const shown = all.filter((t) =>
    filter === "all" ? true : filter === "matched" ? t.status === "matched" : t.status !== "matched");
  const openCount = all.filter((t) => t.status !== "matched").length;

  return (
    <div className="stack">
      <PageHead
        eyebrow={openCount ? `${openCount} åpne` : "Bank"}
        title={<>Bank<em>avstemming</em></>}
        action={
          <button className="icon" aria-label="Oppdater" title="Oppdater" onClick={reload}>
            <RefreshCw size={18} />
          </button>
        }
      />

      <section className="card stack">
        <div className="spread">
          <h2>Kontoutskrift</h2>
          <span className="badge neutral">CAMT.053</span>
        </div>
        <p className="muted small">
          Last ned kontoutskriften som CAMT.053 (XML) fra nettbanken og last den opp her. Samme fil eller
          overlappende perioder gir ingen dobbeltposter.
        </p>
        <input ref={fileRef} type="file" accept=".xml,application/xml,text/xml" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void importFile(f); }} />
        <button className="primary block" disabled={busy} onClick={() => fileRef.current?.click()}>
          {busy ? <span className="spinner" /> : <FileUp size={20} />} Last opp kontoutskrift
        </button>
        {notice && <Notice kind="ok">{notice}</Notice>}
        <ErrorBox error={error ?? recon.error ?? txs.error} />
      </section>

      {(recon.data ?? []).map((r) => (
        <div className="tiles" key={r.bank_account.id}>
          <div className="tile">
            <div className="label"><Landmark size={14} /> Banken {r.as_of ? formatDate(r.as_of) : ""}</div>
            <div className="value">{r.bank_balance_ore == null ? "–" : <Amount ore={r.bank_balance_ore} />}</div>
          </div>
          <div className="tile">
            <div className="label">Regnskapet ({r.bank_account.ledger_account})</div>
            <div className="value">{r.ledger_balance_ore == null ? "–" : <Amount ore={r.ledger_balance_ore} />}</div>
          </div>
          <div className={`tile ${r.difference_ore === 0 ? "sky" : ""}`} style={{ gridColumn: "1 / -1" }}>
            <div className="label">
              {r.difference_ore === 0 ? <><CheckCircle2 size={14} /> Saldoen stemmer</> : "Differanse"}
              {" · konto "}{r.bank_account.account_id}
            </div>
            <div className="value">{r.difference_ore == null ? "Mangler saldo i utskriften" : <Amount ore={r.difference_ore} />}</div>
          </div>
        </div>
      ))}

      <div className="row" role="tablist" aria-label="Filter">
        {([["open", "Åpne"], ["matched", "Avstemt"], ["all", "Alle"]] as [Filter, string][]).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? "primary" : "ghost"}
            style={{ minHeight: 38, padding: "6px 14px" }} onClick={() => setFilter(k)}>{label}</button>
        ))}
      </div>

      {txs.loading ? (
        <Loading />
      ) : all.length === 0 ? (
        <EmptyState icon={<Landmark size={34} />} title="Ingen banklinjer ennå">
          Når du laster opp kontoutskriften, kobler Bokbuzz hver linje til riktig bilag og viser hva som mangler.
        </EmptyState>
      ) : shown.length === 0 ? (
        <EmptyState icon={<CheckCircle2 size={34} />} title="Alt er avstemt" />
      ) : (
        <div className="card list">
          {shown.map((t) => <TxRow key={t.id} cid={cid} t={t} onDecide={decide} />)}
        </div>
      )}
    </div>
  );
}

function TxRow({ cid, t, onDecide }: { cid: string; t: BankTransaction; onDecide: (id: string, ok: boolean) => void }) {
  const st = STATUS[t.status ?? "missing_document"];
  const title = t.counterparty_name ?? t.description ?? (t.amount_ore < 0 ? "Utbetaling" : "Innbetaling");
  return (
    <div className="item" style={{ alignItems: "flex-start" }}>
      <span className="grow stack-sm">
        <span className="title" style={{ display: "block" }}>{title}</span>
        <span className="sub" style={{ display: "block" }}>
          {formatDate(t.booking_date)}
          {t.description && t.description !== title ? ` · ${t.description}` : ""}
          {t.reference ? ` · KID ${t.reference}` : ""}
        </span>
        <span className={`badge ${st.tone}`}>{st.label}</span>
        {t.status === "suggested" && t.match && (
          <span className="stack-sm">
            <span className="muted small" style={{ display: "flex", gap: 6 }}>
              <Sparkles size={14} style={{ flex: "none", marginTop: 3 }} /> {t.match.explanation}
            </span>
            <span className="row">
              <button className="primary" style={{ minHeight: 36, padding: "4px 12px" }}
                onClick={() => onDecide(t.match!.id, true)}>
                <CheckCircle2 size={16} /> Stemmer
              </button>
              <button className="ghost" style={{ minHeight: 36, padding: "4px 12px" }}
                onClick={() => onDecide(t.match!.id, false)}>
                <X size={16} /> Feil bilag
              </button>
            </span>
          </span>
        )}
        {t.status === "matched" && t.voucher && (
          <span className="muted small">Bilag {t.voucher.series}{t.voucher.number}/{t.voucher.year}: {t.voucher.description}</span>
        )}
        {t.status === "proposed" && t.proposal_id && (
          <Link className="button" style={{ alignSelf: "flex-start", minHeight: 36, padding: "4px 12px" }}
            to={`/c/${cid}/innboks/${t.proposal_id}`}>Kontroller forslaget <ChevronRight size={16} /></Link>
        )}
        {t.status === "missing_document" && t.amount_ore < 0 && (
          <Link className="button" style={{ alignSelf: "flex-start", minHeight: 36, padding: "4px 12px" }}
            to={`/c/${cid}/opplasting`}>Last opp kvittering</Link>
        )}
        {t.status === "missing_document" && t.amount_ore > 0 && (
          <span className="muted small">Innbetaling uten bilag. Fakturering kommer i neste versjon.</span>
        )}
      </span>
      <span className="amount" style={{ flex: "none" }}><Amount ore={t.amount_ore} /></span>
    </div>
  );
}
