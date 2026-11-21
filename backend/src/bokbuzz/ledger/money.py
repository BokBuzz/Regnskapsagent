"""Pengeregning i heltall øre. Ingen flyttall i regnskapet."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")


def vat_amount(net_ore: int, rate_bp: int) -> int:
    """MVA av et nettobeløp, avrundet til nærmeste øre (halv øre rundes bort fra null)."""
    product = abs(net_ore) * rate_bp
    rounded = (product + 5000) // 10000
    return rounded if net_ore >= 0 else -rounded


def oslo_date(moment: datetime) -> date:
    """Bokføringsdato i norsk tid. En kvittering 31.12 kl. 23:30 hører til det året."""
    if moment.tzinfo is None:
        raise ValueError("Tidspunktet må ha tidssone")
    return moment.astimezone(OSLO).date()


def oslo_today() -> date:
    return datetime.now(UTC).astimezone(OSLO).date()


def format_nok(ore: int) -> str:
    sign = "-" if ore < 0 else ""
    kr, o = divmod(abs(ore), 100)
    return f"{sign}{kr:,}".replace(",", " ") + f",{o:02d}"
