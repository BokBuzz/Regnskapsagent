import { useState, type FormEvent } from "react";
import { Camera, CheckCheck, ShieldCheck, Sparkles } from "lucide-react";
import { ErrorBox, Logo, Notice } from "../components/ui";
import { useAuth } from "../lib/auth";

export default function LoginPage() {
  const auth = useAuth();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "in") await auth.signIn(email, password);
      else setInfo((await auth.signUp(email, password)) || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const hero = (
    <header className="hero">
      <div style={{ maxWidth: 460, margin: "0 auto" }} className="stack">
        <Logo size={36} light />
        <h1 style={{ marginTop: 28 }}>Regnskap som<br />går av seg selv.</h1>
        <p>For enkeltpersonforetak og aksjeselskap. Ta bilde av kvitteringen, KI-en foreslår, du bokfører.</p>
      </div>
    </header>
  );

  if (auth.mode === "dev") {
    return (
      <>
        {hero}
        <main className="narrow stack">
          <div className="card stack">
            <Notice kind="warn">Lokal modus. Lag et token med <code>python -m bokbuzz.devtoken</code>.</Notice>
            <div>
              <label htmlFor="tok">Utviklertoken</label>
              <textarea id="tok" rows={4} value={token} onChange={(e) => setToken(e.target.value)} />
            </div>
            <button className="primary block" disabled={!token.trim()} onClick={() => auth.devSignIn(token)}>
              Logg inn
            </button>
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      {hero}
      <main className="narrow stack">
        <form className="card stack" onSubmit={submit}>
          <h2>{mode === "in" ? "Logg inn" : "Opprett konto"}</h2>
          <div>
            <label htmlFor="email">E-post</label>
            <input id="email" type="email" autoComplete="email" placeholder="navn@firma.no" required value={email}
              onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label htmlFor="pw">Passord</label>
            <input id="pw" type="password" required minLength={mode === "up" ? 12 : 1}
              autoComplete={mode === "in" ? "current-password" : "new-password"} value={password}
              onChange={(e) => setPassword(e.target.value)} />
            {mode === "up" && <p className="muted small" style={{ marginTop: 6 }}>Minst 12 tegn.</p>}
          </div>
          <ErrorBox error={error} />
          {info && <Notice kind="ok">{info}</Notice>}
          <button className="primary block" type="submit" disabled={busy}>
            {mode === "in" ? "Logg inn" : "Opprett konto"}
          </button>
          <button type="button" className="ghost block" onClick={() => setMode(mode === "in" ? "up" : "in")}>
            {mode === "in" ? "Ny bruker? Opprett konto" : "Har du konto? Logg inn"}
          </button>
        </form>
        <div className="steps">
          <div className="step"><Camera size={22} />Ta bilde</div>
          <div className="step"><Sparkles size={22} />KI foreslår</div>
          <div className="step"><CheckCheck size={22} />Du bokfører</div>
        </div>
        <p className="muted small row" style={{ justifyContent: "center", gap: 6 }}>
          <ShieldCheck size={16} /> Data lagres i EU. Tofaktor-innlogging er påkrevd.
        </p>
      </main>
    </>
  );
}
