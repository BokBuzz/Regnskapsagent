import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { BookCheck, ChevronRight, Undo2 } from "lucide-react";
import { EmptyState, ErrorBox, Loading, PageHead, YearSelect } from "../components/ui";
import { useAuth } from "../lib/auth";
import { formatDate } from "../lib/money";
import { useLoad } from "../lib/useLoad";

export default function VouchersPage() {
  const { cid = "" } = useParams();
  const { api } = useAuth();
  const [year, setYear] = useState(new Date().getFullYear());
  const { data, error, loading } = useLoad(() => api.vouchers(cid, year), [api, cid, year]);

  return (
    <div className="stack">
      <PageHead eyebrow={data?.length ? `${data.length} bilag` : "Hovedbok"} title="Bokførte bilag"
        action={<YearSelect year={year} onChange={setYear} />} />
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : !data?.length ? (
        <EmptyState icon={<BookCheck size={34} />} title={`Ingen bilag i ${year}`}
          action={<Link className="button primary" to={`/c/${cid}/opplasting`}>Last opp første bilag</Link>}>
          Når du har kontrollert og bokført et bilag, finner du det her.
        </EmptyState>
      ) : (
        <div className="card list">
          {[...data].reverse().map((v) => (
            <Link key={v.id} to={v.id} className="item">
              <span className="avatar sm num" style={{ width: "auto", padding: "0 10px" }}>{v.series}{v.number}</span>
              <span className="grow">
                <span className="title" style={{ display: "block" }}>{v.description}</span>
                <span className="sub row" style={{ gap: 6 }}>
                  {formatDate(v.voucher_date)}
                  {v.reverses_voucher_id && <span className="badge neutral"><Undo2 size={12} /> Reversering</span>}
                </span>
              </span>
              <ChevronRight className="chev" size={18} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
