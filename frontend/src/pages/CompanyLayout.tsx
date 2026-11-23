import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { useLoad } from "../lib/useLoad";

export default function CompanyLayout() {
  const { cid = "" } = useParams();
  const { api, signOut } = useAuth();
  const { data: company } = useLoad(() => api.company(cid), [api, cid]);
  const { data: pending } = useLoad(() => api.proposals(cid, "pending"), [api, cid]);

  return (
    <>
      <header className="topbar">
        <div className="inner">
          <Link to="/" className="brand">Bokbuzz</Link>
          <span className="muted" style={{ color: "inherit", opacity: 0.85 }}>{company?.name ?? ""}</span>
          <button onClick={() => void signOut()}>Logg ut</button>
        </div>
      </header>
      <nav className="tabs" aria-label="Hovedmeny">
        <NavLink to="opplasting">Nytt bilag</NavLink>
        <NavLink to="innboks">Til kontroll{pending?.length ? ` (${pending.length})` : ""}</NavLink>
        <NavLink to="bilag">Bokført</NavLink>
        <NavLink to="rapport">Saldo</NavLink>
      </nav>
      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
