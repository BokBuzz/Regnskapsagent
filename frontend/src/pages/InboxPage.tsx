import { Link, useParams } from "react-router-dom";
import { ChevronRight, Inbox, Loader2, PartyPopper, RefreshCw } from "lucide-react";
import { Amount, Avatar, EmptyState, ErrorBox, Loading, PageHead, STATUS_LABEL } from "../components/ui";
import { useAuth } from "../lib/auth";
import { formatDate } from "../lib/money";
import { useLoad } from "../lib/useLoad";

export default function InboxPage() {
  const { cid = "" } = useParams();
  const { api } = useAuth();
  const pending = useLoad(() => api.proposals(cid, "pending"), [api, cid]);
  const manual = useLoad(() => api.proposals(cid, "needs_manual"), [api, cid]);
  const docs = useLoad(() => api.documents(cid), [api, cid]);

  const items = [...(pending.data ?? []), ...(manual.data ?? [])].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );
  const waiting = (docs.data ?? []).filter((d) => d.status === "received").length;
  const reload = () => { void pending.reload(); void manual.reload(); void docs.reload(); };

  return (
    <div className="stack">
      <PageHead
        eyebrow={items.length ? `${items.length} venter` : "Innboks"}
        title={<>Til <em>kontroll</em></>}
        action={
          <button className="icon" aria-label="Oppdater" title="Oppdater" onClick={reload}>
            <RefreshCw size={18} />
          </button>
        }
      />
      <ErrorBox error={pending.error ?? manual.error} />
      {waiting > 0 && (
        <div className="alert">
          <Loader2 size={18} className="spinner" style={{ border: 0 }} />
          <span>{waiting} bilag leses av KI-en. Trykk oppdater om litt.</span>
        </div>
      )}
      {pending.loading || manual.loading ? (
        <Loading />
      ) : items.length === 0 ? (
        <EmptyState
          icon={waiting ? <Inbox size={34} /> : <PartyPopper size={34} />}
          title={waiting ? "Snart klart" : "Alt er kontrollert"}
          action={<Link className="button primary" to={`/c/${cid}/opplasting`}>Last opp kvittering</Link>}
        >
          Nye bilag dukker opp her når KI-en har lest dem.
        </EmptyState>
      ) : (
        <div className="card list">
          {items.map((p) => {
            const name = p.extraction?.supplier_name ?? p.draft?.description ?? "Bilag uten forslag";
            return (
              <Link key={p.id} to={p.id} className="item">
                <Avatar name={name} tone={p.status === "needs_manual" ? "honey" : "brand"} />
                <span className="grow">
                  <span className="title" style={{ display: "block" }}>{p.draft?.description ?? name}</span>
                  <span className="sub" style={{ display: "block" }}>
                    {p.draft ? formatDate(p.draft.voucher_date) : "Mangler opplysninger"}
                    {p.warnings.length > 0 && ` · ${p.warnings.length} merknad${p.warnings.length > 1 ? "er" : ""}`}
                  </span>
                  <span className={`badge ${p.status === "needs_manual" ? "warn" : ""}`} style={{ marginTop: 8 }}>{STATUS_LABEL[p.status]}</span>
                </span>
                {p.extraction?.total_amount_ore != null && (
                  <span className="amount" style={{ flex: "none", alignSelf: "flex-start", marginTop: 4 }}><Amount ore={p.extraction.total_amount_ore} /></span>
                )}
                <ChevronRight className="chev" size={18} />
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
