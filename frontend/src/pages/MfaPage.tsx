import { useEffect, useState, type FormEvent } from "react";
import { KeyRound } from "lucide-react";
import { ErrorBox, Logo } from "../components/ui";
import { useAuth } from "../lib/auth";

export default function MfaPage() {
  const auth = useAuth();
  const [enroll, setEnroll] = useState<{ factorId: string; qrSvg: string; secret: string } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const needsEnroll = auth.state.status === "needs_mfa_enroll";

  useEffect(() => {
    if (needsEnroll && !enroll) {
      auth.enrollMfa().then(setEnroll, (e) => setError(e.message));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsEnroll]);

  const factorId =
    auth.state.status === "needs_mfa_verify" ? auth.state.factorId : enroll?.factorId ?? null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!factorId) return;
    setBusy(true);
    setError(null);
    try {
      await auth.verifyMfa(factorId, code.replace(/\s/g, ""));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="narrow stack">
      <Logo />
      <div className="row" style={{ marginTop: 24 }}>
        <span className="avatar"><KeyRound size={20} /></span>
        <h1>Tofaktor-innlogging</h1>
      </div>
      {needsEnroll ? (
        <>
          <p>Regnskapet ditt er beskyttet med en ekstra kode. Skann QR-koden med en autentiseringsapp
            (for eksempel Google Authenticator eller Microsoft Authenticator).</p>
          {enroll && (
            <div className="card stack">
              <div className="qr"><img src={enroll.qrSvg} alt="QR-kode for autentiseringsappen" /></div>
              <p className="muted">Kan du ikke skanne? Skriv inn nøkkelen: <code>{enroll.secret}</code></p>
            </div>
          )}
        </>
      ) : (
        <p>Skriv inn den sekssifrede koden fra autentiseringsappen.</p>
      )}
      <form className="card stack" onSubmit={submit}>
        <div>
          <label htmlFor="code">Kode</label>
          <input id="code" style={{ fontSize: "1.5rem", letterSpacing: "0.3em", textAlign: "center" }} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" required
            value={code} onChange={(e) => setCode(e.target.value)} />
        </div>
        <ErrorBox error={error} />
        <button className="primary block" disabled={busy || !factorId}>Bekreft</button>
      </form>
      <button className="ghost block" onClick={() => void auth.signOut()}>Logg ut</button>
    </main>
  );
}
