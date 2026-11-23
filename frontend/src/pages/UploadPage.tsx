import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Camera, CheckCircle2, FileUp, Lightbulb, XCircle } from "lucide-react";
import { ErrorBox, PageHead } from "../components/ui";
import { useAuth } from "../lib/auth";

interface Result {
  name: string;
  ok: boolean;
  text: string;
}

export default function UploadPage() {
  const { cid = "" } = useParams();
  const { api } = useAuth();
  const camera = useRef<HTMLInputElement>(null);
  const files = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function send(list: FileList | null) {
    if (!list?.length) return;
    setBusy(true);
    setError(null);
    const out: Result[] = [];
    for (const file of Array.from(list)) {
      try {
        const doc = await api.upload(cid, file);
        out.push({
          name: file.name,
          ok: true,
          text: doc.duplicate ? "Allerede lastet opp tidligere" : "Mottatt. KI-en leser bilaget nå.",
        });
      } catch (e) {
        out.push({ name: file.name, ok: false, text: e instanceof Error ? e.message : String(e) });
      }
    }
    setResults((prev) => [...out, ...prev]);
    setBusy(false);
    if (camera.current) camera.current.value = "";
    if (files.current) files.current.value = "";
  }

  return (
    <div className="stack">
      <PageHead eyebrow="Nytt bilag" title="Hva har du kjøpt?" />
      <section className="capture-card stack">
        <span className="avatar honey" style={{ width: 52, height: 52, borderRadius: 16, background: "var(--honey)", color: "var(--ink)" }}>
          <Camera size={26} />
        </span>
        <h2>Ta bilde av kvitteringen</h2>
        <p>Eller velg PDF og bilder fra telefonen. Vi leser dato, beløp, leverandør og MVA for deg.</p>
        <div className="row">
          <button className="honey" disabled={busy} onClick={() => camera.current?.click()}>
            {busy ? <span className="spinner" /> : <Camera size={20} />} Ta bilde
          </button>
          <button disabled={busy} onClick={() => files.current?.click()}>
            <FileUp size={20} /> Velg filer
          </button>
        </div>
        <input ref={camera} type="file" accept="image/*" capture="environment" hidden
          onChange={(e) => void send(e.target.files)} />
        <input ref={files} type="file" accept="image/jpeg,image/png,image/webp,image/heic,application/pdf"
          multiple hidden onChange={(e) => void send(e.target.files)} />
      </section>
      <ErrorBox error={error} />
      {results.length > 0 && (
        <div className="card list">
          {results.map((r, i) => (
            <div key={i} className="item" style={{ display: "flex", gap: 12, alignItems: "center", padding: 12 }}>
              <span className={`avatar sm ${r.ok ? "" : "honey"}`} style={r.ok ? { background: "var(--ok-bg)", color: "var(--ok)" } : undefined}>
                {r.ok ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
              </span>
              <span className="grow">
                <span className="title" style={{ display: "block" }}>{r.name}</span>
                <span className="sub">{r.text}</span>
              </span>
            </div>
          ))}
        </div>
      )}
      {results.some((r) => r.ok) && (
        <Link className="button primary block" to={`/c/${cid}/innboks`}>
          Gå til kontroll <ArrowRight size={18} />
        </Link>
      )}
      <div className="card tinted row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
        <Lightbulb size={20} style={{ color: "var(--warn)", flex: "none", marginTop: 2 }} />
        <p className="small muted">
          <strong style={{ color: "var(--text)" }}>Tips:</strong> Legg kvitteringen på et mørkt underlag og få med hele
          lappen. Originalen lagres i fem år, slik bokføringsloven krever.
        </p>
      </div>
    </div>
  );
}
