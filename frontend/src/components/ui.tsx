import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { formatOre } from "../lib/money";

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="alert error" role="alert">
      <XCircle size={18} aria-hidden />
      <span>{error}</span>
    </div>
  );
}

const NOTICE_ICON = { info: Info, warn: AlertTriangle, ok: CheckCircle2 };

export function Notice({ kind = "info", children }: { kind?: "info" | "warn" | "ok"; children: ReactNode }) {
  const Icon = NOTICE_ICON[kind];
  return (
    <div className={`alert ${kind}`}>
      <Icon size={18} aria-hidden />
      <div>{children}</div>
    </div>
  );
}

export function Amount({ ore, className = "" }: { ore: number; className?: string }) {
  return <span className={`num ${ore < 0 ? "neg" : ""} ${className}`}>{formatOre(ore)}</span>;
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack-sm" aria-busy="true" aria-label="Laster">
      {Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" />)}
    </div>
  );
}

/** Bikube-logoen: sekskant i honning med en «b». */
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <path d="M32 3l25 14.5v29L32 61 7 46.5v-29z" fill="#ffb020" />
      <path d="M24 17h6v11.2a10 10 0 1 1-6 9.2zm10 15.2a5.2 5.2 0 1 0 0 10.4 5.2 5.2 0 0 0 0-10.4z" fill="#17132b" />
    </svg>
  );
}

export function Logo({ size = 32, light = false }: { size?: number; light?: boolean }) {
  return (
    <span className="logo" style={light ? { color: "#fff" } : undefined}>
      <LogoMark size={size} />
      <span>Bokbuzz</span>
    </span>
  );
}

export function PageHead({ eyebrow, title, action }: { eyebrow?: string; title: string; action?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="card empty">
      <div className="art">{icon}</div>
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Avatar({ name, tone = "brand", small = false }: { name: string; tone?: "brand" | "honey"; small?: boolean }) {
  const initials = name
    .replace(/\b(AS|ASA|ENK|DA|ANS)\b/gi, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("") || "?";
  return <span className={`avatar ${tone === "honey" ? "honey" : ""} ${small ? "sm" : ""}`} aria-hidden>{initials}</span>;
}

export function YearSelect({ year, onChange }: { year: number; onChange: (y: number) => void }) {
  const now = new Date().getFullYear();
  return (
    <select aria-label="År" value={year} onChange={(e) => onChange(Number(e.target.value))}
      style={{ width: "auto", borderRadius: 999, minHeight: 40, padding: "6px 14px", fontWeight: 700 }}>
      {[0, 1, 2].map((d) => <option key={now - d} value={now - d}>{now - d}</option>)}
    </select>
  );
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
