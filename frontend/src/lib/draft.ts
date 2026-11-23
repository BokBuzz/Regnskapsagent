// Skjemamodell for kontroll av et bilag, i kundens språk: kostnadslinjer + «betalt fra».
// Gjøres om til et bilagsutkast (debet/kredit) som backend validerer på nytt.

import type { DraftLine, VoucherDraft } from "./api";
import { vatAmount } from "./money";

export interface FormLine {
  account: string;
  description: string;
  netOre: number | null;
  vatCode: string;
  /** MVA-beløpet fra kvitteringen; nullstilles når brukeren endrer beløp eller kode. */
  vatOre: number | null;
}

export interface VoucherForm {
  date: string;
  description: string;
  lines: FormLine[];
  paymentAccount: string;
}

export const PAYMENT_ACCOUNTS: { number: string; label: string }[] = [
  { number: "1920", label: "Bankkonto (næring)" },
  { number: "2070", label: "Betalt privat" },
  { number: "1900", label: "Kontant" },
  { number: "2400", label: "Ikke betalt ennå (leverandørgjeld)" },
];

export function emptyForm(): VoucherForm {
  return {
    date: "",
    description: "",
    lines: [{ account: "", description: "", netOre: null, vatCode: "1", vatOre: null }],
    paymentAccount: "1920",
  };
}

export function formFromDraft(draft: VoucherDraft | null): VoucherForm {
  if (!draft) return emptyForm();
  const lines = [...draft.lines];
  let paymentAccount = "1920";
  const last = lines[lines.length - 1];
  if (last && !last.vat_code && last.amount_ore < 0 && lines.length > 1) {
    paymentAccount = last.account;
    lines.pop();
  }
  return {
    date: draft.voucher_date,
    description: draft.description,
    paymentAccount,
    lines: lines.map((l) => ({
      account: l.account,
      description: l.description ?? "",
      netOre: l.amount_ore,
      vatCode: l.vat_code ?? "0",
      vatOre: l.vat_amount_ore ?? null,
    })),
  };
}

export function lineVat(line: FormLine, rates: Record<string, number>): number {
  if (line.netOre === null) return 0;
  if (line.vatOre !== null) return line.vatOre;
  return vatAmount(line.netOre, rates[line.vatCode] ?? 0);
}

export function formTotal(form: VoucherForm, rates: Record<string, number>): number {
  return form.lines.reduce((sum, l) => sum + (l.netOre ?? 0) + lineVat(l, rates), 0);
}

export function formErrors(form: VoucherForm): string[] {
  const errs: string[] = [];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.date)) errs.push("Velg bilagsdato.");
  if (!form.description.trim()) errs.push("Skriv en kort beskrivelse.");
  form.lines.forEach((l, i) => {
    if (!l.account) errs.push(`Linje ${i + 1}: velg konto.`);
    if (l.netOre === null || l.netOre === 0) errs.push(`Linje ${i + 1}: fyll inn beløp uten MVA.`);
  });
  return errs;
}

export function draftFromForm(form: VoucherForm, rates: Record<string, number>): VoucherDraft {
  const lines: DraftLine[] = form.lines.map((l) => ({
    account: l.account,
    amount_ore: l.netOre ?? 0,
    vat_code: l.vatCode === "0" ? null : l.vatCode,
    vat_amount_ore: l.vatCode === "0" ? null : l.vatOre,
    description: l.description.trim() || null,
  }));
  lines.push({ account: form.paymentAccount, amount_ore: -formTotal(form, rates), description: "Betaling" });
  return { voucher_date: form.date, description: form.description.trim(), lines };
}
