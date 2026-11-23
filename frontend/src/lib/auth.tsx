// Innlogging. I produksjon: Supabase Auth med påkrevd tofaktor (TOTP).
// Lokalt (VITE_AUTH_MODE=dev): lim inn et utviklertoken fra `python -m bokbuzz.devtoken`.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Api } from "./api";

export type AuthState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "needs_mfa_enroll" }
  | { status: "needs_mfa_verify"; factorId: string }
  | { status: "ready"; email: string | null };

interface AuthApi {
  state: AuthState;
  api: Api;
  mode: "supabase" | "dev";
  signIn(email: string, password: string): Promise<void>;
  signUp(email: string, password: string): Promise<string>;
  enrollMfa(): Promise<{ factorId: string; qrSvg: string; secret: string }>;
  verifyMfa(factorId: string, code: string): Promise<void>;
  devSignIn(token: string): void;
  signOut(): Promise<void>;
}

const Ctx = createContext<AuthApi | null>(null);
const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const MODE: "supabase" | "dev" = import.meta.env.VITE_AUTH_MODE === "dev" ? "dev" : "supabase";
const DEV_KEY = "bokbuzz.devtoken";

let supabase: SupabaseClient | null = null;
function sb(): SupabaseClient {
  if (!supabase) {
    const url = import.meta.env.VITE_SUPABASE_URL;
    const key = import.meta.env.VITE_SUPABASE_ANON_KEY;
    if (!url || !key) throw new Error("VITE_SUPABASE_URL og VITE_SUPABASE_ANON_KEY må settes");
    supabase = createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true } });
  }
  return supabase;
}

function readDevToken(): string | null {
  try {
    return sessionStorage.getItem(DEV_KEY);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const refresh = useCallback(async () => {
    if (MODE === "dev") {
      setState(readDevToken() ? { status: "ready", email: "utvikler" } : { status: "signed_out" });
      return;
    }
    const { data } = await sb().auth.getSession();
    if (!data.session) return setState({ status: "signed_out" });
    const aal = await sb().auth.mfa.getAuthenticatorAssuranceLevel();
    if (aal.data?.currentLevel === "aal2") {
      return setState({ status: "ready", email: data.session.user.email ?? null });
    }
    const factors = await sb().auth.mfa.listFactors();
    const totp = factors.data?.totp.find((f) => f.status === "verified");
    setState(totp ? { status: "needs_mfa_verify", factorId: totp.id } : { status: "needs_mfa_enroll" });
  }, []);

  useEffect(() => {
    void refresh();
    if (MODE === "dev") return;
    const { data } = sb().auth.onAuthStateChange(() => void refresh());
    return () => data.subscription.unsubscribe();
  }, [refresh]);

  const api = useMemo(
    () =>
      new Api(API_URL, async () => {
        if (MODE === "dev") return readDevToken();
        const { data } = await sb().auth.getSession();
        return data.session?.access_token ?? null;
      }),
    [],
  );

  const value: AuthApi = {
    state,
    api,
    mode: MODE,
    async signIn(email, password) {
      const { error } = await sb().auth.signInWithPassword({ email, password });
      if (error) throw new Error("Feil e-post eller passord");
      await refresh();
    },
    async signUp(email, password) {
      const { data, error } = await sb().auth.signUp({ email, password });
      if (error) throw new Error(error.message);
      await refresh();
      return data.session ? "" : "Sjekk e-posten din og bekreft adressen før du logger inn.";
    },
    async enrollMfa() {
      // Fjern halvferdige faktorer fra tidligere forsøk, så enroll ikke feiler.
      const existing = await sb().auth.mfa.listFactors();
      for (const f of existing.data?.all ?? []) {
        if (f.status === "unverified") await sb().auth.mfa.unenroll({ factorId: f.id });
      }
      const { data, error } = await sb().auth.mfa.enroll({ factorType: "totp", friendlyName: "Bokbuzz" });
      if (error || !data || data.type !== "totp") throw new Error("Kunne ikke starte tofaktor");
      return { factorId: data.id, qrSvg: data.totp.qr_code, secret: data.totp.secret };
    },
    async verifyMfa(factorId, code) {
      const { error } = await sb().auth.mfa.challengeAndVerify({ factorId, code });
      if (error) throw new Error("Feil kode. Prøv igjen med koden som vises nå.");
      await refresh();
    },
    devSignIn(token) {
      try {
        sessionStorage.setItem(DEV_KEY, token.trim());
      } catch {
        /* privat modus */
      }
      void refresh();
    },
    async signOut() {
      if (MODE === "dev") {
        try {
          sessionStorage.removeItem(DEV_KEY);
        } catch {
          /* ignorer */
        }
      } else {
        await sb().auth.signOut();
      }
      await refresh();
    },
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth utenfor AuthProvider");
  return v;
}
