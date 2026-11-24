"""Kontrollsiffer for norske identifikatorer (mod11)."""

from __future__ import annotations

_FNR_K1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
_FNR_K2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
_ACCOUNT = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]


def _mod11(digits: list[int], weights: list[int]) -> int | None:
    rest = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11
    check = 0 if rest == 0 else 11 - rest
    return None if check == 10 else check


def valid_national_id(value: str) -> bool:
    """Fødselsnummer eller d-nummer (11 siffer, to kontrollsiffer). Syntetiske testnumre fra
    Tenor har måned + 80 og godtas, siden kontrollsifrene er like."""
    if len(value) != 11 or not value.isdigit():
        return False
    d = [int(c) for c in value]
    k1 = _mod11(d[:9], _FNR_K1)
    if k1 is None or k1 != d[9]:
        return False
    k2 = _mod11(d[:10], _FNR_K2)
    return k2 is not None and k2 == d[10]


def valid_bank_account(value: str) -> bool:
    """Norsk kontonummer (11 siffer, mod11)."""
    if len(value) != 11 or not value.isdigit():
        return False
    d = [int(c) for c in value]
    check = _mod11(d[:10], _ACCOUNT)
    return check is not None and check == d[10]


def clean_digits(value: str) -> str:
    return "".join(c for c in value if c.isdigit())
