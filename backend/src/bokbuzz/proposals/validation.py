"""Deterministiske kontroller av modellens svar. Modellens egen «sikkerhet»
brukes ikke som terskel; bare regler som kan testes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..ledger.money import vat_amount
from .schema import Extraction

PURCHASE_ACCOUNT_TYPES = {"expense", "asset"}
VAT_TOLERANCE_ORE = 1


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    escalate: bool = False  # True: en sterkere modell kan trolig løse det

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def valid_orgnr(orgnr: str) -> bool:
    """Mod11-kontroll av norsk organisasjonsnummer."""
    if len(orgnr) != 9 or not orgnr.isdigit():
        return False
    weights = [3, 2, 7, 6, 5, 4, 3, 2]
    rest = sum(int(d) * w for d, w in zip(orgnr[:8], weights, strict=True)) % 11
    check = 0 if rest == 0 else 11 - rest
    return check != 10 and check == int(orgnr[8])


def validate(
    ex: Extraction,
    *,
    accounts: dict[str, dict],
    vat_rates: dict[str, tuple[int, str]],
    today: date,
) -> tuple[list[Finding], list[Finding]]:
    """Returnerer (feil, advarsler). vat_rates: kode -> (sats i bp, retning) på bilagsdatoen."""
    errors: list[Finding] = []
    warnings: list[Finding] = []

    if ex.document_kind in ("settlement", "other"):
        errors.append(Finding("manual_kind", "Denne dokumenttypen konteres manuelt foreløpig"))
    if ex.currency != "NOK":
        errors.append(Finding("foreign_currency", "Utenlandsk valuta krever manuell kontering foreløpig"))
    if ex.document_date is None:
        errors.append(Finding("missing_date", "Bilaget mangler dato"))
    elif ex.document_date > today + timedelta(days=1):
        errors.append(Finding("future_date", "Bilagsdatoen er frem i tid"))
    elif ex.document_date < today - timedelta(days=730):
        warnings.append(Finding("old_date", "Bilaget er mer enn to år gammelt"))

    total = sum(line.net_amount_ore + line.vat_amount_ore for line in ex.lines)
    if total != ex.total_amount_ore:
        errors.append(Finding("sum_mismatch",
                              f"Linjene summerer til {total} øre, men totalen er {ex.total_amount_ore} øre",
                              escalate=True))

    sign = -1 if ex.document_kind == "credit_note" else 1
    for i, line in enumerate(ex.lines, start=1):
        if line.net_amount_ore == 0 or (line.net_amount_ore > 0) != (sign > 0):
            errors.append(Finding("line_sign", f"Linje {i} har feil fortegn eller er 0", escalate=True))
        acc = accounts.get(line.account)
        if acc is None:
            errors.append(Finding("unknown_account", f"Linje {i}: konto {line.account} finnes ikke",
                                  escalate=True))
        elif acc["account_type"] not in PURCHASE_ACCOUNT_TYPES:
            errors.append(Finding("account_type", f"Linje {i}: konto {line.account} kan ikke brukes på kjøp",
                                  escalate=True))
        rate = vat_rates.get(line.vat_code)
        if rate is None:
            errors.append(Finding("unknown_vat_code", f"Linje {i}: MVA-kode {line.vat_code} er ugyldig",
                                  escalate=True))
            continue
        rate_bp, direction = rate
        if direction == "output":
            errors.append(Finding("vat_direction", f"Linje {i}: utgående MVA-kode på et kjøp", escalate=True))
            continue
        expected = vat_amount(line.net_amount_ore, rate_bp) if direction == "input" else 0
        if abs(line.vat_amount_ore - expected) > VAT_TOLERANCE_ORE:
            errors.append(Finding("vat_mismatch",
                                  f"Linje {i}: MVA {line.vat_amount_ore} øre, forventet {expected} øre",
                                  escalate=True))

    if not ex.supplier_name:
        warnings.append(Finding("missing_supplier", "Leverandørens navn mangler på bilaget"))
    if ex.supplier_orgnr is None:
        warnings.append(Finding("missing_orgnr", "Leverandørens org.nr. mangler på bilaget"))
    elif not valid_orgnr(ex.supplier_orgnr.replace(" ", "")):
        warnings.append(Finding("invalid_orgnr", "Leverandørens org.nr. er ugyldig (mod11)"))
    if ex.payment == "unknown":
        warnings.append(Finding("payment_unknown", "Betalingsmåte er ukjent; foreslår bankkonto"))
    if ex.ambiguous:
        warnings.append(Finding("ambiguous", "Modellen er usikker: " + "; ".join(ex.ambiguity_reasons)))
    return errors, warnings
