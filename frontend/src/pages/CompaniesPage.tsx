import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Building2, CarTaxiFront, ChevronRight, LogOut, Plus, Search, User } from "lucide-react";
import { Avatar, ErrorBox, Loading, Logo, Notice } from "../components/ui";
import type { Entity, Module, OrgForm } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLoad } from "../lib/useLoad";

const ORG_FORM_LABEL: Record<string, string> = { ENK: "Enkeltpersonforetak", AS: "Aksjeselskap" };

export default function CompaniesPage() {
  const { api, signOut } = useAuth();
  const { data, error, loading } = useLoad(() => api.companies(), [api]);
  const [adding, setAdding] = useState(false);

  if (loading) return <main className="narrow"><Loading /></main>;
  if (data && data.length === 1 && !adding) return <Navigate to={`/c/${data[0].id}`} replace />;
  const first = !data?.length;

  return (
    <main className="narrow stack">
      <div className="spread">
        <Logo />
        <button className="ghost icon" aria-label="Logg ut" title="Logg ut" onClick={() => void signOut()}>
          <LogOut size={20} />
        </button>
      </div>
      <div style={{ marginTop: 28 }}>
        <div className="muted small" style={{ fontWeight: 700, color: "var(--brand)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          {first ? "Steg 1 av 1" : "Dine regnskap"}
        </div>
        <h1>{first ? "Kom i gang" : "Velg selskap"}</h1>
        {first && <p className="muted" style={{ marginTop: 6 }}>Det tar under ett minutt. Vi henter opplysningene fra Brønnøysund.</p>}
      </div>
      <ErrorBox error={error} />
      {data && data.length > 0 && (
        <div className="card list">
          {data.map((c) => (
            <Link key={c.id} className="item" to={`/c/${c.id}`}>
              <Avatar name={c.name} />
              <span className="grow">
                <span className="title" style={{ display: "block" }}>{c.name}</span>
                <span className="sub">{ORG_FORM_LABEL[c.org_form] ?? c.org_form} · {c.orgnr}</span>
              </span>
              <ChevronRight className="chev" size={20} />
            </Link>
          ))}
        </div>
      )}
      {data && (first || adding) ? (
        <Onboarding />
      ) : (
        <button className="block" onClick={() => setAdding(true)}><Plus size={18} /> Legg til selskap</button>
      )}
    </main>
  );
}

function Onboarding() {
  const { api } = useAuth();
  const nav = useNavigate();
  const [orgnr, setOrgnr] = useState("");
  const [entity, setEntity] = useState<Entity | null>(null);
  const [looked, setLooked] = useState(false);
  const [name, setName] = useState("");
  const [orgForm, setOrgForm] = useState<OrgForm>("ENK");
  const [taxi, setTaxi] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const known = entity?.org_form === "ENK" || entity?.org_form === "AS";
  const unsupported = !!entity && !known;

  async function lookup(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const found = await api.lookup(orgnr.replace(/\s/g, ""));
      setEntity(found);
      setName(found.name);
      if (found.org_form === "ENK" || found.org_form === "AS") setOrgForm(found.org_form);
    } catch (err) {
      // Oppslaget er en hjelp, ikke et krav: brukeren kan fylle ut selv.
      setEntity(null);
      setError(err instanceof Error ? err.message : String(err));
      setName("");
    } finally {
      setLooked(true);
      setBusy(false);
    }
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const modules: Module[] = taxi ? ["taxi"] : [];
      const c = await api.createCompany({
        orgnr: orgnr.replace(/\s/g, ""), name, org_form: orgForm, modules,
        vat_registered: entity ? entity.vat_registered : true,
      });
      nav(`/c/${c.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <section className="card stack">
      <h2>Registrer foretaket ditt</h2>
      <form onSubmit={lookup}>
        <label htmlFor="orgnr">Organisasjonsnummer</label>
        <input id="orgnr" inputMode="numeric" placeholder="9 siffer" required value={orgnr}
          onChange={(e) => setOrgnr(e.target.value)} />
        <button disabled={busy} className="block" style={{ marginTop: 10 }}>
          {busy ? <span className="spinner" /> : <Search size={18} />}
          Hent fra Brønnøysund
        </button>
      </form>
      {entity && (
        <div className="supplier">
          <Avatar name={entity.name} tone="honey" />
          <div className="grow">
            <strong>{entity.name}</strong>
            <div className="muted small">
              {ORG_FORM_LABEL[entity.org_form] ?? entity.org_form}
              {entity.address ? ` · ${entity.address}` : ""}
            </div>
            <div className="row" style={{ marginTop: 6, gap: 6 }}>
              <span className={`badge ${entity.vat_registered ? "ok" : "neutral"}`}>
                {entity.vat_registered ? "MVA-registrert" : "Ikke MVA-registrert"}
              </span>
              {entity.deleted && <span className="badge warn">Slettet</span>}
            </div>
          </div>
        </div>
      )}
      {unsupported && (
        <Notice kind="warn">
          Bokbuzz støtter foreløpig enkeltpersonforetak (ENK) og aksjeselskap (AS). Denne enheten er {entity?.org_form}.
        </Notice>
      )}
      {error && <Notice kind="warn">{error}. Du kan fylle ut selv.</Notice>}
      {looked && (
        <div className="stack">
          <div>
            <label htmlFor="name">Navn</label>
            <input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label id="orgform-label">Selskapsform</label>
            <div className="choice-grid" role="group" aria-labelledby="orgform-label">
              {(["ENK", "AS"] as const).map((f) => (
                <button key={f} type="button" className="choice" aria-pressed={orgForm === f}
                  data-orgform={f} disabled={known && orgForm !== f} onClick={() => setOrgForm(f)}>
                  <span className="ico">{f === "ENK" ? <User size={18} /> : <Building2 size={18} />}</span>
                  <strong>{f === "ENK" ? "ENK" : "AS"}</strong>
                  <span className="muted">{ORG_FORM_LABEL[f]}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <label>Bransjetillegg <span className="muted" style={{ fontWeight: 500 }}>(valgfritt)</span></label>
            <label className="toggle-card check">
              <input type="checkbox" checked={taxi} onChange={(e) => setTaxi(e.target.checked)} />
              <span className="grow">
                <strong style={{ display: "block" }}>Drosje</strong>
                <span className="muted small">Kontoer for kjøreinntekter, taxisentral og oppgjør</span>
              </span>
              <CarTaxiFront size={22} className="muted" />
            </label>
          </div>
          <label className="check confirm">
            <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
            <span>Jeg forstår at jeg selv kontrollerer og bokfører hvert bilag. Bokbuzz foreslår, men fører
              ikke regnskapet for meg.</span>
          </label>
          <button className="primary block" disabled={busy || !name.trim() || !accepted || unsupported}
            onClick={() => void create()}>
            Opprett regnskap
          </button>
        </div>
      )}
    </section>
  );
}
