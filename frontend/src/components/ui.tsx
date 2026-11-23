import type { ReactNode } from "react";
import { formatOre } from "../lib/money";

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="alert error" role="alert">
      {error}
    </div>
  );
}

export function Notice({ kind = "info", children }: { kind?: "info" | "warn" | "ok"; children: ReactNode }) {
  return <div className={`alert ${kind}`}>{children}</div>;
}

export function Amount({ ore, className = "" }: { ore: number; className?: string }) {
  return <span className={`num ${ore < 0 ? "neg" : ""} ${className}`}>{formatOre(ore)}</span>;
}

export function Loading() {
  return <p className="muted">Laster …</p>;
}

export const STATUS_LABEL: Record<string, string> = {
  pending: "Klar til kontroll",
  needs_manual: "Må fylles ut",
  approved: "Bokført",
  rejected: "Avvist",
  received: "Mottatt",
  extracted: "Lest",
  proposed: "Forslag klart",
  posted: "Bokført",
};
