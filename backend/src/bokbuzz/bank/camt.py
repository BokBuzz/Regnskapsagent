"""Leser kontoutskrifter i ISO 20022 CAMT.053 (alle versjoner fra .001.02).

Norske banker leverer CAMT.053 fra nettbanken. Parseren bruker defusedxml (ingen
eksterne entiteter, ingen entitetsbomber) og leser elementene etter lokalt navn,
så den tåler både camt.053.001.02 og nyere versjoner.

Bare bokførte poster (status BOOK) tas med. Beløp gjøres om til heltall øre
uten flyttall."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

from ..errors import ValidationFailed

MAX_ENTRIES = 20_000


@dataclass(frozen=True)
class CamtEntry:
    booking_date: date
    value_date: date | None
    amount_ore: int  # inn +, ut -
    currency: str
    counterparty_name: str | None
    counterparty_account: str | None
    reference: str | None
    end_to_end_id: str | None
    description: str | None
    bank_ref: str | None
    bank_tx_code: str | None
    fingerprint: str = ""


@dataclass(frozen=True)
class CamtStatement:
    account_id: str
    currency: str
    statement_ref: str | None
    from_date: date | None
    to_date: date | None
    opening_balance_ore: int | None
    closing_balance_ore: int | None
    entries: list[CamtEntry] = field(default_factory=list)

    @property
    def balance_ok(self) -> bool | None:
        if self.opening_balance_ore is None or self.closing_balance_ore is None:
            return None
        return self.opening_balance_ore + sum(e.amount_ore for e in self.entries) == self.closing_balance_ore


# ---------------------------------------------------------------------------
# Hjelpere for navnerom-uavhengig lesing
# ---------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: Element | None, *path: str) -> Element | None:
    for name in path:
        if el is None:
            return None
        el = next((c for c in el if _local(c.tag) == name), None)
    return el


def _children(el: Element | None, name: str) -> list[Element]:
    return [] if el is None else [c for c in el if _local(c.tag) == name]


def _text(el: Element | None, *path: str) -> str | None:
    node = _child(el, *path)
    if node is None or node.text is None:
        return None
    value = " ".join(node.text.split())
    return value or None


def _date(el: Element | None) -> date | None:
    """Leser <Dt> eller <DtTm> under elementet."""
    raw = _text(el, "Dt")
    if raw:
        return date.fromisoformat(raw[:10])
    raw = _text(el, "DtTm")
    if raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    return None


def to_ore(raw: str | None) -> int:
    if raw is None:
        raise ValidationFailed("Beløp mangler i kontoutskriften", code="camt_invalid")
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ValidationFailed(f"Ugyldig beløp i kontoutskriften: {raw!r}", code="camt_invalid") from exc
    ore = value * 100
    if ore != ore.to_integral_value() or abs(ore) > 10**15:
        raise ValidationFailed(f"Beløpet {raw} kan ikke gjøres om til øre", code="camt_invalid")
    return int(ore)


def _signed(amount_el: Element | None, indicator: str | None) -> tuple[int, str]:
    if amount_el is None:
        raise ValidationFailed("Beløp mangler i kontoutskriften", code="camt_invalid")
    ore = to_ore(amount_el.text)
    if indicator == "DBIT":
        ore = -ore
    elif indicator != "CRDT":
        raise ValidationFailed("Ukjent debet/kredit-markering i kontoutskriften", code="camt_invalid")
    return ore, (amount_el.get("Ccy") or "NOK").upper()


def _account_id(acct: Element | None) -> str | None:
    raw = _text(acct, "Id", "IBAN") or _text(acct, "Id", "Othr", "Id")
    return "".join(raw.split()).upper() if raw else None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _balance(stmt: Element, codes: tuple[str, ...]) -> int | None:
    for bal in _children(stmt, "Bal"):
        code = _text(bal, "Tp", "CdOrPrtry", "Cd")
        if code in codes:
            return _signed(_child(bal, "Amt"), _text(bal, "CdtDbtInd"))[0]
    return None


def _status(entry: Element) -> str | None:
    # .001.02–.001.07: <Sts>BOOK</Sts>; .001.08 og senere: <Sts><Cd>BOOK</Cd></Sts>
    return _text(entry, "Sts", "Cd") or _text(entry, "Sts")


def _tx_code(entry: Element) -> str | None:
    bk = _child(entry, "BkTxCd")
    domain = _text(bk, "Domn", "Cd")
    if domain:
        parts = [domain, _text(bk, "Domn", "Fmly", "Cd"), _text(bk, "Domn", "Fmly", "SubFmlyCd")]
        return "/".join(p for p in parts if p)
    return _text(bk, "Prtry", "Cd")


def _entry(entry: Element) -> CamtEntry:
    amount, currency = _signed(_child(entry, "Amt"), _text(entry, "CdtDbtInd"))
    booking = _date(_child(entry, "BookgDt")) or _date(_child(entry, "ValDt"))
    if booking is None:
        raise ValidationFailed("En post i kontoutskriften mangler bokføringsdato", code="camt_invalid")
    tx = _child(entry, "NtryDtls", "TxDtls")
    parties = _child(tx, "RltdPties")
    # Motparten er mottakeren ved utbetaling og betaleren ved innbetaling.
    if amount < 0:
        name = _text(parties, "Cdtr", "Nm") or _text(parties, "Cdtr", "Pty", "Nm")
        acct = _account_id(_child(parties, "CdtrAcct"))
    else:
        name = _text(parties, "Dbtr", "Nm") or _text(parties, "Dbtr", "Pty", "Nm")
        acct = _account_id(_child(parties, "DbtrAcct"))
    rmt = _child(tx, "RmtInf")
    reference = _text(rmt, "Strd", "CdtrRefInf", "Ref")
    ustrd = " ".join(t for t in (" ".join((u.text or "").split()) for u in _children(rmt, "Ustrd")) if t)
    description = ustrd or _text(tx, "AddtlTxInf") or _text(entry, "AddtlNtryInf")
    e2e = _text(tx, "Refs", "EndToEndId")
    if e2e == "NOTPROVIDED":
        e2e = None
    return CamtEntry(
        booking_date=booking, value_date=_date(_child(entry, "ValDt")), amount_ore=amount,
        currency=currency, counterparty_name=name[:200] if name else None, counterparty_account=acct,
        reference=reference[:100] if reference else None, end_to_end_id=e2e[:100] if e2e else None,
        description=description[:500] if description else None,
        bank_ref=(_text(entry, "AcctSvcrRef") or _text(tx, "Refs", "AcctSvcrRef")),
        bank_tx_code=_tx_code(entry),
    )


def _with_fingerprints(entries: list[CamtEntry]) -> list[CamtEntry]:
    """Bankens referanse når den finnes. Ellers en hash av innholdet, nummerert når to
    poster er like, slik at samme post i to overlappende utskrifter får samme nøkkel."""
    seen: Counter[str] = Counter()
    out: list[CamtEntry] = []
    for e in entries:
        if e.bank_ref:
            base = "ref:" + e.bank_ref
        else:
            blob = "|".join(str(x or "") for x in (e.booking_date, e.amount_ore, e.currency, e.counterparty_name,
                                                   e.counterparty_account, e.reference, e.end_to_end_id,
                                                   e.description))
            base = "h:" + hashlib.sha256(blob.encode()).hexdigest()[:32]
        seen[base] += 1
        fp = base if seen[base] == 1 else f"{base}#{seen[base]}"
        out.append(CamtEntry(**{**e.__dict__, "fingerprint": fp}))
    return out


def parse_camt053(data: bytes) -> list[CamtStatement]:
    try:
        root = SafeET.fromstring(data)
    except Exception as exc:  # defusedxml og expat kaster flere ulike typer
        raise ValidationFailed("Filen er ikke gyldig XML", code="camt_invalid") from exc
    ns = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    if _local(root.tag) != "Document" or "camt.053" not in ns:
        raise ValidationFailed("Filen er ikke en CAMT.053-kontoutskrift", code="camt_invalid")
    body = _child(root, "BkToCstmrStmt")
    statements: list[CamtStatement] = []
    total = 0
    for stmt in _children(body, "Stmt"):
        acct = _child(stmt, "Acct")
        account_id = _account_id(acct)
        if not account_id:
            raise ValidationFailed("Kontoutskriften mangler kontonummer", code="camt_invalid")
        entries = []
        for ntry in _children(stmt, "Ntry"):
            if _status(ntry) != "BOOK":
                continue
            entries.append(_entry(ntry))
        total += len(entries)
        if total > MAX_ENTRIES:
            raise ValidationFailed("Kontoutskriften har for mange poster", code="camt_too_large")
        period = _child(stmt, "FrToDt")
        from_dt = _text(period, "FrDtTm")
        to_dt = _text(period, "ToDtTm")
        statements.append(CamtStatement(
            account_id=account_id,
            currency=(_text(acct, "Ccy") or "NOK").upper(),
            statement_ref=_text(stmt, "Id"),
            from_date=date.fromisoformat(from_dt[:10]) if from_dt else None,
            to_date=date.fromisoformat(to_dt[:10]) if to_dt else None,
            opening_balance_ore=_balance(stmt, ("OPBD", "PRCD")),
            closing_balance_ore=_balance(stmt, ("CLBD",)),
            entries=_with_fingerprints(entries),
        ))
    if not statements:
        raise ValidationFailed("Fant ingen kontoutskrift i filen", code="camt_invalid")
    return statements
