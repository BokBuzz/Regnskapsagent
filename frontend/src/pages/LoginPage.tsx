import { useState, type FormEvent } from "react";
import { ErrorBox, Notice } from "../components/ui";
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

  if (auth.mode === "dev") {
    return (
      <main className="narrow stack">
        <h1>Bokbuzz (utvikling)</h1>
        <Notice kind="warn">Lokal modus. Lag et token med <code>python -m bokbuzz.devtoken</code>.</Notice>
        <label htmlFor="tok">Utviklertoken</label>
        <textarea id="tok" rows={4} value={token} onChange={(e) => setToken(e.target.value)} />
        <button className="primary" disabled={!token.trim()} onClick={() => auth.devSignIn(token)}>
          Logg inn
        </button>
      </main>
    );
  }

  return (
    <main className="narrow stack">
      <h1>{mode === "in" ? "Logg inn på Bokbuzz" : "Opprett konto"}</h1>
      <p className="muted">Regnskap for enkeltpersonforetak og aksjeselskap. Ta bilde av kvitteringen, kontroller forslaget, bokfør.</p>
      <form className="card stack" onSubmit={submit}>
        <div>
          <label htmlFor="email">E-post</label>
          <input id="email" type="email" autoComplete="email" required value={email}
            onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="pw">Passord</label>
          <input id="pw" type="password" required minLength={mode === "up" ? 12 : 1}
            autoComplete={mode === "in" ? "current-password" : "new-password"} value={password}
            onChange={(e) => setPassword(e.target.value)} />
          {mode === "up" && <p className="muted">Minst 12 tegn.</p>}
        </div>
        <ErrorBox error={error} />
        {info && <Notice kind="ok">{info}</Notice>}
        <button className="primary" type="submit" disabled={busy}>
          {mode === "in" ? "Logg inn" : "Opprett konto"}
        </button>
      </form>
      <button type="button" onClick={() => setMode(mode === "in" ? "up" : "in")}>
        {mode === "in" ? "Ny bruker? Opprett konto" : "Har du konto? Logg inn"}
      </button>
    </main>
  );
}
