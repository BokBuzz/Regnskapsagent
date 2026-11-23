import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ErrorBox, Loading, Notice } from "../components/ui";
import type { Entity, Module, OrgForm } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLoad } from "../lib/useLoad";

export default function CompaniesPage() {
  const { api, signOut } = useAuth();
  const { data, error, loading } = useLoad(() => api.companies(), [api]);
  const [adding, setAdding] = useState(false);

  if (loading) return <main className="page"><Loading /></main>;
  if (data && data.length === 1 && !adding) return <Navigate to={`/c/${data[0].id}`} replace />;

  return (
    <main className="narrow stack">
      <div className="spread">
        <h1>{data?.length ? "Velg selskap" : "Kom i gang"}</h1>
        <button onClick={() => void signOut()}>Logg ut</button>
      </div>
      <ErrorBox error={error} />
      {data && data.length > 0 && (
        <div className="card list">
          {data.map((c) => (
            <Link key={c.id} className="item" to={`/c/${c.id}`}>
              <span>{c.name}</span>
              <span className="muted num">{c.orgnr}</span>
            </Link>
          ))}
        </div>
      )}
      {data && (data.length === 0 || adding) ? (
        <Onboarding />
      ) : (
        <button onClick={() => setAdding(true)}>Legg til selskap</button>
      )}
    </main>
  );
}

function Onboarding() {
  const { api } = useAuth();
  const nav = useNavigate();
  const [orgnr, setOrgnr] = useState("");
  const [entity, setEntity] = useState<Entity | null>(null);
  const [name, setName] = useState("");
  const [orgForm, setOrgForm] = useState<OrgForm>("ENK");
  const [taxi, setTaxi] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      // Oppslaget er en hjelp, ikke et krav: brukeren kan skrive navnet selv.
      setEntity(null);
      setError(err instanceof Error ? err.message : String(err));
      setName("");
    } finally {
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
      <form className="stack" onSubmit={lookup}>
        <div>
          <label htmlFor="orgnr">Organisasjonsnummer</label>
          <input id="orgnr" inputMode="numeric" placeholder="9 siffer" required value={orgnr}
            onChange={(e) => setOrgnr(e.target.value)} />
        </div>
        <button disabled={busy}>Hent fra Brønnøysund</button>
      </form>
      {entity && (
        <Notice kind={entity.deleted ? "warn" : "ok"}>
          <strong>{entity.name}</strong> ({entity.org_form}){entity.address ? `, ${entity.address}` : ""}.{" "}
          {entity.vat_registered ? "Registrert i MVA-registeret." : "Ikke registrert i MVA-registeret."}
          {entity.deleted && " Enheten er slettet i Enhetsregisteret."}
        </Notice>
      )}
      {entity && entity.org_form !== "ENK" && entity.org_form !== "AS" && (
        <Notice kind="warn">
          Bokbuzz støtter foreløpig enkeltpersonforetak (ENK) og aksjeselskap (AS). Denne enheten er {entity.org_form}.
        </Notice>
      )}
      <ErrorBox error={error} />
      {(entity || error) && (
        <div className="stack">
          <div>
            <label htmlFor="name">Navn</label>
            <input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label htmlFor="orgform">Selskapsform</label>
            <select id="orgform" value={orgForm} onChange={(e) => setOrgForm(e.target.value as OrgForm)}
              disabled={entity?.org_form === "ENK" || entity?.org_form === "AS"}>
              <option value="ENK">Enkeltpersonforetak (ENK)</option>
              <option value="AS">Aksjeselskap (AS)</option>
            </select>
          </div>
          <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="muted">Bransjetillegg (valgfritt)</legend>
            <label className="check">
              <input type="checkbox" checked={taxi} onChange={(e) => setTaxi(e.target.checked)} />
              <span>Drosje: kontoer for kjøreinntekter, taxisentral og oppgjør</span>
            </label>
          </fieldset>
          <label className="check">
            <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
            <span>Jeg forstår at jeg selv kontrollerer og bokfører hvert bilag. Bokbuzz foreslår, men fører
              ikke regnskapet for meg.</span>
          </label>
          <button className="primary" disabled={busy || !name.trim() || !accepted ||
              (!!entity && entity.org_form !== "ENK" && entity.org_form !== "AS")} onClick={() => void create()}>
            Opprett regnskap
          </button>
        </div>
      )}
    </section>
  );
}
