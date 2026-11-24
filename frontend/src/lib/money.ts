// Alle beløp i appen er heltall i øre, som i backend. Ingen flyttall i regnskapet.

export function formatOre(ore: number): string {
  const sign = ore < 0 ? "−" : "";
  const abs = Math.abs(ore);
  const kr = Math.floor(abs / 100)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const o = (abs % 100).toString().padStart(2, "0");
  return `${sign}${kr},${o}`;
}

/** Tolker "1 234,50", "1234.5", "-12" osv. til øre. Returnerer null hvis ugyldig. */
export function parseKroner(input: string): number | null {
  const s = input.replace(/[\s ]/g, "").replace("−", "-").replace(",", ".");
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) return null;
  const negative = s.startsWith("-");
  const [kr, frac = ""] = s.replace("-", "").split(".");
  const ore = Number(kr) * 100 + Number(frac.padEnd(2, "0"));
  if (!Number.isSafeInteger(ore)) return null;
  return negative ? -ore : ore;
}

/** MVA av nettobeløp i øre, avrundet som i backend (halv øre bort fra null). */
export function vatAmount(netOre: number, rateBp: number): number {
  const rounded = Math.floor((Math.abs(netOre) * rateBp + 5000) / 10000);
  return netOre < 0 ? -rounded : rounded;
}

export function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}
