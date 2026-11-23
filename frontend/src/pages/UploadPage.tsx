import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorBox, Notice } from "../components/ui";
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
          text: doc.duplicate ? "Allerede lastet opp tidligere" : "Mottatt. Forslaget kommer i «Til kontroll».",
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
      <h1>Nytt bilag</h1>
      <div className="card drop stack">
        <p>Ta bilde av kvitteringen, eller velg PDF eller bilder fra telefonen.</p>
        <div className="row" style={{ justifyContent: "center" }}>
          <button className="primary" disabled={busy} onClick={() => camera.current?.click()}>
            Ta bilde
          </button>
          <button disabled={busy} onClick={() => files.current?.click()}>
            Velg filer
          </button>
        </div>
        <input ref={camera} type="file" accept="image/*" capture="environment" hidden
          onChange={(e) => void send(e.target.files)} />
        <input ref={files} type="file" accept="image/jpeg,image/png,image/webp,image/heic,application/pdf"
          multiple hidden onChange={(e) => void send(e.target.files)} />
        {busy && <p className="muted">Laster opp …</p>}
      </div>
      <ErrorBox error={error} />
      {results.map((r, i) => (
        <Notice key={i} kind={r.ok ? "ok" : "warn"}>
          <strong>{r.name}</strong>: {r.text}
        </Notice>
      ))}
      {results.some((r) => r.ok) && (
        <p>
          <Link to={`/c/${cid}/innboks`}>Gå til bilag som venter på kontroll</Link>
        </p>
      )}
    </div>
  );
}
