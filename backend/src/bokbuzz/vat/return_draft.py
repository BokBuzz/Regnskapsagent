"""MVA-melding: beregning per termin fra hovedboken, kontroller før innsending og
XML etter Skatteetatens format.

Beregningen er ren regelkode. Innsending skjer aldri herfra: kunden logger inn med
ID-porten og sender selv (se submission.py og docs/MVA_MELDING.md).

VERIFISER mot Skatteetatens validerings-API i testmiljøet før første ekte innsending:
fortegn på fradragslinjer, om grunnlag skal oppgis for fradragskoder, avrunding og
elementnavn for årstermin. Dette er merket i koden der det gjelder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID
from xml.sax.saxutils import escape

from ..db import Conn
from ..errors import ValidationFailed

BIMONTHLY_NAMES = ["januar-februar", "mars-april", "mai-juni", "juli-august", "september-oktober",
                   "november-desember"]
XML_NS = "no:skatteetaten:fastsetting:avgift:mva:skattemeldingformerverdiavgift:v1.0"
SYSTEM_NAME = "Bokbuzz"


@dataclass(frozen=True)
class Term:
    year: int
    term: int  # 1–6 for tomånedlig, 1 for årlig
    kind: str  # "bimonthly" eller "annual"

    @property
    def start(self) -> date:
        return date(self.year, 1, 1) if self.kind == "annual" else date(self.year, 2 * self.term - 1, 1)

    @property
    def end(self) -> date:
        if self.kind == "annual" or self.term == 6:
            return date(self.year, 12, 31)
        return date(self.year, 2 * self.term + 1, 1) - timedelta(days=1)

    @property
    def label(self) -> str:
        return f"{BIMONTHLY_NAMES[self.term - 1]} {self.year}" if self.kind == "bimonthly" else f"år {self.year}"

    @property
    def due(self) -> date:
        """Frist for MVA-meldingen. Tomånedlig: 10. i andre måned etter terminen, men termin 3
        har frist 31. august. Årlig: 10. mars året etter. (Verifiser mot skatteetaten.no.)"""
        if self.kind == "annual":
            return date(self.year + 1, 3, 10)
        if self.term == 3:
            return date(self.year, 8, 31)
        if self.term == 6:
            return date(self.year + 1, 2, 10)
        return date(self.year, 2 * self.term + 2, 10)


def term_for(company: dict, year: int, term: int) -> Term:
    kind = company["vat_term"]
    limit = 1 if kind == "annual" else 6
    if not 1 <= term <= limit:
        raise ValidationFailed(f"Termin må være mellom 1 og {limit}", code="invalid_term")
    return Term(year, term, kind)


def _kroner(ore: int) -> str:
    return str((Decimal(ore) / 100).quantize(Decimal("0.01")))


def compute(conn: Conn, company_id: UUID, year: int, term: int) -> dict:
    company = conn.execute("select * from bokbuzz.companies where id = %s", [company_id]).fetchone()
    if not company["vat_registered"]:
        raise ValidationFailed("Selskapet er ikke registrert i Merverdiavgiftsregisteret", code="not_vat_registered")
    t = term_for(company, year, term)

    # Grunnlag: linjer med MVA-kode som ikke selv er MVA-linjer. MVA: linjene hovedboken la til.
    rows = conn.execute(
        "select l.vat_code as code, c.direction, c.description,"
        " sum(case when l.vat_base_line_no is null then l.amount_ore else 0 end)::bigint as base_ore,"
        " sum(case when l.vat_base_line_no is not null then l.amount_ore else 0 end)::bigint as vat_ore"
        " from bokbuzz.voucher_lines l join bokbuzz.vouchers v on v.id = l.voucher_id"
        " join bokbuzz.vat_codes c on c.code = l.vat_code"
        " where l.company_id = %s and v.voucher_date between %s and %s and c.direction <> 'none'"
        " group by l.vat_code, c.direction, c.description order by l.vat_code::int",
        [company_id, t.start, t.end],
    ).fetchall()
    lines = []
    for r in rows:
        rate = conn.execute(
            "select rate_bp from bokbuzz.vat_rates where code = %s and valid_from <= %s"
            " and (valid_to is null or valid_to >= %s)", [r["code"], t.end, t.end],
        ).fetchone()
        # I meldingen er utgående avgift positiv og fradrag negativt. I hovedboken er salg og
        # utgående MVA kredit (negativt), kjøp og inngående MVA debet (positivt). Derfor snus fortegnet.
        base = -r["base_ore"]
        vat = -r["vat_ore"]
        if base == 0 and vat == 0:
            continue
        lines.append({"code": r["code"], "description": r["description"], "direction": r["direction"],
                      "rate_bp": rate["rate_bp"] if rate else None, "base_ore": base, "vat_ore": vat})
    total = sum(ln["vat_ore"] for ln in lines)
    return {
        "company": {"id": company["id"], "orgnr": company["orgnr"], "name": company["name"]},
        "year": year, "term": term, "kind": t.kind, "label": t.label,
        "from": t.start, "to": t.end, "due": t.due,
        "lines": lines, "total_ore": total,
        "result": "to_pay" if total > 0 else ("refund" if total < 0 else "zero"),
        "checks": checks(conn, company_id, t),
    }


def checks(conn: Conn, company_id: UUID, t: Term) -> list[dict]:
    """Det MVA-agenten sjekker før kunden sender: ting som gjør meldingen feil eller ufullstendig."""
    out: list[dict] = []
    pending = conn.execute(
        "select count(*)::int as n from bokbuzz.proposals p"
        " left join bokbuzz.bank_transactions t on t.id = p.bank_transaction_id"
        " where p.company_id = %s and p.status in ('pending', 'needs_manual')"
        " and (p.draft is null or (p.draft->>'voucher_date')::date between %s and %s"
        "      or t.booking_date between %s and %s)",
        [company_id, t.start, t.end, t.start, t.end],
    ).fetchone()["n"]
    if pending:
        out.append({"code": "pending_proposals", "severity": "error",
                    "message": f"{pending} bilag venter på kontroll. De må bokføres eller avvises først."})
    missing = conn.execute(
        "select count(*)::int as n from bokbuzz.bank_transactions t where t.company_id = %s"
        " and t.booking_date between %s and %s"
        " and not exists (select 1 from bokbuzz.bank_matches m where m.transaction_id = t.id"
        "                 and m.status = 'confirmed')",
        [company_id, t.start, t.end],
    ).fetchone()["n"]
    if missing:
        out.append({"code": "unreconciled_bank", "severity": "warning",
                    "message": f"{missing} banklinjer i terminen er ikke avstemt. Det kan bety bilag som mangler."})
    cover = conn.execute(
        "select min(from_date) as first, max(to_date) as last from bokbuzz.bank_statements where company_id = %s",
        [company_id],
    ).fetchone()
    if cover["first"] is None or cover["first"] > t.start or cover["last"] < t.end:
        out.append({"code": "bank_not_imported", "severity": "warning",
                    "message": "Kontoutskriften er ikke importert for hele terminen."})
    closed = conn.execute(
        "select count(*)::int as n from bokbuzz.periods where company_id = %s and status = 'open'"
        " and make_date(year, month, 1) between %s and %s",
        [company_id, t.start, t.end],
    ).fetchone()["n"]
    if closed:
        out.append({"code": "periods_open", "severity": "info",
                    "message": "Månedene i terminen er ikke lukket. Lukk dem etter innsending, så tallene "
                               "ikke kan endres."})
    return out


def to_xml(draft: dict, *, system_version: str, reference: str) -> str:
    """MVA-meldingen som XML (mvaMeldingDto). VERIFISER mot Skatteetatens XSD og validerings-API."""
    period_el = ("skattleggingsperiodeToMaaneder" if draft["kind"] == "bimonthly"
                 else "skattleggingsperiodeAarlig")
    period_val = BIMONTHLY_NAMES[draft["term"] - 1] if draft["kind"] == "bimonthly" else "aarlig"
    spec = []
    for ln in draft["lines"]:
        parts = [f"<mvaKode>{escape(ln['code'])}</mvaKode>"]
        if ln["direction"] == "output":  # grunnlag oppgis for utgående koder
            parts.append(f"<grunnlag>{_kroner(ln['base_ore'])}</grunnlag>")
            if ln["rate_bp"] is not None:
                parts.append(f"<sats>{Decimal(ln['rate_bp']) / 100:g}</sats>")
        parts.append(f"<merverdiavgift>{_kroner(ln['vat_ore'])}</merverdiavgift>")
        spec.append("<mvaSpesifikasjonslinje>" + "".join(parts) + "</mvaSpesifikasjonslinje>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<mvaMeldingDto xmlns="{XML_NS}">'
        "<innsending>"
        f"<regnskapssystemsreferanse>{escape(reference)}</regnskapssystemsreferanse>"
        f"<regnskapssystem><systemnavn>{SYSTEM_NAME}</systemnavn>"
        f"<systemversjon>{escape(system_version)}</systemversjon></regnskapssystem>"
        "</innsending>"
        "<skattegrunnlagOgBeregnetSkatt>"
        f"<skattleggingsperiode><periode><{period_el}>{period_val}</{period_el}></periode>"
        f"<aar>{draft['year']}</aar></skattleggingsperiode>"
        f"<fastsattMerverdiavgift>{_kroner(draft['total_ore'])}</fastsattMerverdiavgift>"
        + "".join(spec) +
        "</skattegrunnlagOgBeregnetSkatt>"
        f"<skattepliktig><organisasjonsnummer>{escape(draft['company']['orgnr'])}</organisasjonsnummer>"
        "</skattepliktig>"
        "<meldingskategori>alminnelig</meldingskategori>"
        "</mvaMeldingDto>"
    )
