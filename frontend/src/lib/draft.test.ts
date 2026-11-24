import type { VoucherDraft } from "./api";
import { draftFromForm, formErrors, formFromDraft, formTotal, paymentAccounts } from "./draft";

const rates = { "0": 0, "1": 2500, "13": 1200 };

const proposal: VoucherDraft = {
  voucher_date: "2026-03-10",
  description: "Circle K – Diesel",
  lines: [
    { account: "7000", amount_ore: 50000, vat_code: "1", vat_amount_ore: 12500, description: "Diesel" },
    { account: "1920", amount_ore: -62500, description: "Betalt (bank)" },
  ],
};

test("forslag blir kostnadslinjer + betalingskonto, og tilbake i balanse", () => {
  const form = formFromDraft(proposal);
  expect(form.paymentAccount).toBe("1920");
  expect(form.lines).toHaveLength(1);
  expect(formTotal(form, rates)).toBe(62500);
  const draft = draftFromForm(form, rates);
  const sum = draft.lines.reduce((s, l) => s + l.amount_ore + (l.vat_amount_ore ?? 0), 0);
  expect(sum).toBe(0);
});

test("endret beløp gir ny MVA beregnet som i backend", () => {
  const form = formFromDraft(proposal);
  form.lines[0] = { ...form.lines[0], netOre: 10000, vatOre: null };
  expect(formTotal(form, rates)).toBe(12500);
  form.paymentAccount = "2070";
  const draft = draftFromForm(form, rates);
  expect(draft.lines.at(-1)).toEqual({ account: "2070", amount_ore: -12500, description: "Betaling" });
});

test("mangler gir feilmeldinger", () => {
  const errs = formErrors(formFromDraft(null));
  expect(errs.join(" ")).toMatch(/dato/);
  expect(errs.join(" ")).toMatch(/konto/);
});

test("betalt privat går til 2070 i ENK og 2910 i AS", () => {
  expect(paymentAccounts("ENK").map((p) => p.number)).toContain("2070");
  const as = paymentAccounts("AS").map((p) => p.number);
  expect(as).toContain("2910");
  expect(as).not.toContain("2070");
});
