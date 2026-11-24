"""Regler for banklinjer som banken selv dokumenterer: gebyrer og renter.

For slike poster er kontoutskriften dokumentasjonen, så Bokbuzz kan foreslå et bilag
direkte fra banklinjen. Alt annet (kjøp, salg, overføringer) krever et eget bilag og
blir i stedet flagget som «mangler bilag» til kunden laster det opp.

Reglene er bevisst strenge: bankens transaksjonskode eller et entydig ord i teksten.
Er vi i tvil, lager vi ikke forslag."""

from __future__ import annotations

import re
from dataclasses import dataclass

RULES_VERSION = "bank-rules-v1"


@dataclass(frozen=True)
class BankRule:
    key: str
    account: str
    direction: str  # "out" eller "in": hvilken vei pengene må gå for at regelen gjelder
    label: str
    why: str


FEE = BankRule("fee", "7770", "out", "Bankgebyr",
               "Banken har merket posten som gebyr. Bankgebyrer føres på 7770 Bank- og kortgebyrer, "
               "og finansielle tjenester er unntatt merverdiavgift, så det er ingen MVA.")
INTEREST_IN = BankRule("interest_income", "8050", "in", "Renteinntekt",
                       "Banken har merket posten som renter inn på kontoen. Renteinntekter føres på 8050 "
                       "Renteinntekter og har ikke merverdiavgift.")
INTEREST_OUT = BankRule("interest_cost", "8150", "out", "Rentekostnad",
                        "Banken har merket posten som renter belastet kontoen. Rentekostnader føres på 8150 "
                        "Rentekostnader og har ikke merverdiavgift.")

# ISO 20022 banktransaksjonskoder (Domain/Family/SubFamily).
_FEE_CODES = ("/CHRG", "/COMM", "/FEES")
_INTEREST_CODES = ("/INTR",)

_FEE_WORDS = re.compile(r"\b(gebyr|gebyrer|omkostning(er)?|årsavgift kort|kortavgift|termingebyr)\b", re.I)
_INTEREST_WORDS = re.compile(r"\b(renter|rente|kreditrente(r)?|debetrente(r)?|renteinntekt(er)?)\b", re.I)


def classify(amount_ore: int, bank_tx_code: str | None, description: str | None) -> BankRule | None:
    code = (bank_tx_code or "").upper()
    text = description or ""
    outgoing = amount_ore < 0
    is_fee = code.endswith(_FEE_CODES) or bool(_FEE_WORDS.search(text))
    is_interest = code.endswith(_INTEREST_CODES) or bool(_INTEREST_WORDS.search(text))
    if is_fee and is_interest:
        return None  # tvetydig
    if is_fee and outgoing:
        return FEE
    if is_interest:
        return INTEREST_OUT if outgoing else INTEREST_IN
    return None
