"""Betalingsfil etter ISO 20022 pain.001.001.03 (Customer Credit Transfer Initiation).

Kunden laster filen opp i nettbanken og godkjenner betalingene der med BankID. Bokbuzz
flytter aldri penger selv.

VERIFISER med kundens bank før første ekte bruk: norske banker har egne krav til
filopplasting (avtale, BIC, kontoformat). Filen bruker norske kontonumre (BBAN),
KID som strukturert referanse (SCOR) og formålskode SALA for lønn."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape

NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"


@dataclass(frozen=True)
class Payment:
    end_to_end_id: str
    amount_ore: int
    creditor_name: str
    creditor_account: str
    kid: str | None = None
    message: str | None = None
    salary: bool = False


def _kr(ore: int) -> str:
    return str((Decimal(ore) / 100).quantize(Decimal("0.01")))


def _acct(account: str) -> str:
    return f"<Id><Othr><Id>{escape(account)}</Id><SchmeNm><Cd>BBAN</Cd></SchmeNm></Othr></Id>"


def build(*, message_id: str, debtor_name: str, debtor_account: str, execution_date: date,
          payments: list[Payment], created: datetime) -> str:
    if not payments:
        raise ValueError("Ingen betalinger")
    if any(p.amount_ore <= 0 for p in payments):
        raise ValueError("Alle betalinger må være positive")
    total = sum(p.amount_ore for p in payments)
    txs = []
    for p in payments:
        purpose = "<Purp><Cd>SALA</Cd></Purp>" if p.salary else ""
        if p.kid:
            rmt = ("<RmtInf><Strd><CdtrRefInf><Tp><CdOrPrtry><Cd>SCOR</Cd></CdOrPrtry></Tp>"
                   f"<Ref>{escape(p.kid)}</Ref></CdtrRefInf></Strd></RmtInf>")
        else:
            rmt = f"<RmtInf><Ustrd>{escape((p.message or '')[:140])}</Ustrd></RmtInf>"
        txs.append(
            "<CdtTrfTxInf>"
            f"<PmtId><EndToEndId>{escape(p.end_to_end_id[:35])}</EndToEndId></PmtId>"
            f'<Amt><InstdAmt Ccy="NOK">{_kr(p.amount_ore)}</InstdAmt></Amt>'
            f"<Cdtr><Nm>{escape(p.creditor_name[:70])}</Nm></Cdtr>"
            f"<CdtrAcct>{_acct(p.creditor_account)}</CdtrAcct>"
            f"{purpose}{rmt}"
            "</CdtTrfTxInf>"
        )
    category = "<PmtTpInf><CtgyPurp><Cd>SALA</Cd></CtgyPurp></PmtTpInf>" if all(p.salary for p in payments) else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Document xmlns="{NS}"><CstmrCdtTrfInitn>'
        "<GrpHdr>"
        f"<MsgId>{escape(message_id[:35])}</MsgId>"
        f"<CreDtTm>{created.strftime('%Y-%m-%dT%H:%M:%S')}</CreDtTm>"
        f"<NbOfTxs>{len(payments)}</NbOfTxs><CtrlSum>{_kr(total)}</CtrlSum>"
        f"<InitgPty><Nm>{escape(debtor_name[:70])}</Nm></InitgPty>"
        "</GrpHdr>"
        "<PmtInf>"
        f"<PmtInfId>{escape(message_id[:35])}</PmtInfId><PmtMtd>TRF</PmtMtd>"
        f"<NbOfTxs>{len(payments)}</NbOfTxs><CtrlSum>{_kr(total)}</CtrlSum>"
        f"{category}"
        f"<ReqdExctnDt>{execution_date.isoformat()}</ReqdExctnDt>"
        f"<Dbtr><Nm>{escape(debtor_name[:70])}</Nm></Dbtr>"
        f"<DbtrAcct>{_acct(debtor_account)}</DbtrAcct>"
        "<DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></DbtrAgt>"
        + "".join(txs) +
        "</PmtInf></CstmrCdtTrfInitn></Document>"
    )
