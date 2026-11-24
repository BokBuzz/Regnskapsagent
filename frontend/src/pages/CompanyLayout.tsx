import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { BookCheck, Camera, Inbox, LogOut, PieChart } from "lucide-react";
import { LogoMark } from "../components/ui";
import { useAuth } from "../lib/auth";
import { useLoad } from "../lib/useLoad";

const ORG_FORM_LABEL: Record<string, string> = { ENK: "Enkeltpersonforetak", AS: "Aksjeselskap" };

export default function CompanyLayout() {
  const { cid = "" } = useParams();
  const { api, signOut } = useAuth();
  const { data: company } = useLoad(() => api.company(cid), [api, cid]);
  const { data: pending } = useLoad(() => api.proposals(cid, "pending"), [api, cid]);

  return (
    <>
      <header className="topbar">
        <div className="inner">
          <Link to="/" aria-label="Bokbuzz, alle selskaper" style={{ display: "flex" }}><LogoMark size={28} /></Link>
          <Link to="/" className="company-chip" title="Bytt selskap">
            <span style={{ minWidth: 0 }}>
              <span className="name" style={{ display: "block" }}>{company?.name ?? " "}</span>
              <span className="form">{company ? ORG_FORM_LABEL[company.org_form] ?? company.org_form : " "}
                {company?.modules?.includes("taxi") ? " · Drosje" : ""}</span>
            </span>
          </Link>
          <button className="ghost icon" aria-label="Logg ut" title="Logg ut" onClick={() => void signOut()}>
            <LogOut size={20} />
          </button>
        </div>
      </header>
      <nav className="tabs" aria-label="Hovedmeny">
        <NavLink to="opplasting" className="capture"><Camera size={22} />Nytt bilag</NavLink>
        <NavLink to="innboks">
          <Inbox size={22} />Til kontroll
          {pending?.length ? <span className="count">{pending.length}</span> : null}
        </NavLink>
        <NavLink to="bilag"><BookCheck size={22} />Bokført</NavLink>
        <NavLink to="rapport"><PieChart size={22} />Saldo</NavLink>
      </nav>
      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
