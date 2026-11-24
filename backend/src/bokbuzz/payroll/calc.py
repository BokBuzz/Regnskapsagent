"""Lønnsberegning (L0). Ren regelkode uten database, så den kan testes med faste eksempler.

VERIFISER mot Skatteetaten og regnskapsfører før første ekte lønnskjøring:
- prosenttrekk avrundes ned til hele kroner,
- feriepenger og arbeidsgiveravgift avrundes til nærmeste øre,
- tabelltrekk beregnes ikke ennå; beløpet må legges inn fra Skatteetatens trekktabell (kommer i L2),
- frikort behandles som 0 i trekk, uten kontroll av frikortgrensen,
- fribeløpet i sone 1a følges ikke opp ennå.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ledger.money import vat_amount as _round_bp  # samme avrunding: halv øre bort fra null


@dataclass(frozen=True)
class EmployeeTerms:
    pay_type: str                  # monthly | hourly
    monthly_salary_ore: int | None
    hourly_rate_ore: int | None
    tax_card_kind: str             # percent | table | none
    tax_percent: int | None


@dataclass(frozen=True)
class LineInput:
    hours_x100: int | None = None
    bonus_ore: int = 0
    base_override_ore: int | None = None
    tax_override_ore: int | None = None


@dataclass(frozen=True)
class LineResult:
    hours_x100: int | None
    base_ore: int
    bonus_ore: int
    gross_ore: int
    tax_ore: int
    tax_manual: bool
    holiday_pay_ore: int
    aga_ore: int
    aga_holiday_ore: int
    net_ore: int
    problems: tuple[str, ...]


def apply_bp(amount_ore: int, rate_bp: int) -> int:
    return _round_bp(amount_ore, rate_bp)


def percent_tax(gross_ore: int, percent: int) -> int:
    """Prosenttrekk, avrundet ned til hele kroner."""
    return (gross_ore * percent // 100) // 100 * 100


def calculate(terms: EmployeeTerms, inp: LineInput, *, aga_rate_bp: int, holiday_rate_bp: int) -> LineResult:
    problems: list[str] = []
    if inp.base_override_ore is not None:
        base = inp.base_override_ore
    elif terms.pay_type == "monthly":
        base = terms.monthly_salary_ore or 0
    else:
        hours = inp.hours_x100 or 0
        base = ((terms.hourly_rate_ore or 0) * hours + 50) // 100
        if hours == 0:
            problems.append("Timer mangler for timelønnet ansatt")
    gross = base + inp.bonus_ore

    manual = inp.tax_override_ore is not None
    if manual:
        tax = inp.tax_override_ore or 0
    elif terms.tax_card_kind == "percent":
        tax = percent_tax(gross, terms.tax_percent or 0)
    elif terms.tax_card_kind == "table":
        tax = 0
        problems.append("Tabellkort: legg inn trekket fra Skatteetatens trekktabell")
    else:
        tax = 0
    if tax > gross:
        problems.append("Skattetrekket er større enn bruttolønnen")
        tax = gross

    holiday = apply_bp(gross, holiday_rate_bp)
    return LineResult(
        hours_x100=inp.hours_x100, base_ore=base, bonus_ore=inp.bonus_ore, gross_ore=gross, tax_ore=tax,
        tax_manual=manual, holiday_pay_ore=holiday, aga_ore=apply_bp(gross, aga_rate_bp),
        aga_holiday_ore=apply_bp(holiday, aga_rate_bp), net_ore=gross - tax, problems=tuple(problems),
    )
