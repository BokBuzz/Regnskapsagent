import { Link, useParams } from "react-router-dom";
import { Amount, ErrorBox, Loading, STATUS_LABEL } from "../components/ui";
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

  return (
    <div className="stack">
      <div className="spread">
        <h1>Til kontroll</h1>
        <button onClick={() => { void pending.reload(); void manual.reload(); void docs.reload(); }}>Oppdater</button>
      </div>
      <ErrorBox error={pending.error ?? manual.error} />
      {waiting > 0 && <p className="muted">{waiting} bilag leses fortsatt. Oppdater om litt.</p>}
      {pending.loading || manual.loading ? (
        <Loading />
      ) : items.length === 0 ? (
        <p className="muted">Ingen bilag venter. Last opp en kvittering under «Nytt bilag».</p>
      ) : (
        <div className="card list" style={{ padding: 0 }}>
          {items.map((p) => (
            <Link key={p.id} to={p.id} className="item">
              <span className="stack" style={{ gap: 2 }}>
                <strong>{p.draft?.description ?? p.extraction?.supplier_name ?? "Bilag uten forslag"}</strong>
                <span className="muted">
                  {p.draft ? formatDate(p.draft.voucher_date) : "Må fylles ut"}
                  {p.warnings.length > 0 && ` · ${p.warnings.length} merknad${p.warnings.length > 1 ? "er" : ""}`}
                </span>
              </span>
              <span className="stack right" style={{ gap: 2 }}>
                {p.extraction?.total_amount_ore != null && <Amount ore={p.extraction.total_amount_ore} />}
                <span className={`badge ${p.status === "needs_manual" ? "warn" : ""}`}>{STATUS_LABEL[p.status]}</span>
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
