"""Rene enhetstester uten database."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from bokbuzz.documents.filetypes import sniff_mime
from bokbuzz.ledger.money import format_nok, oslo_date, vat_amount
from bokbuzz.proposals.validation import valid_orgnr


def test_new_years_eve_receipt_belongs_to_old_year():
    # 31.12 kl. 23:30 norsk tid er 22:30 UTC samme dag; 00:30 norsk tid 1.1 er 23:30 UTC 31.12.
    assert oslo_date(datetime(2026, 12, 31, 22, 30, tzinfo=UTC)) == date(2026, 12, 31)
    assert oslo_date(datetime(2026, 12, 31, 23, 30, tzinfo=UTC)) == date(2027, 1, 1)
    with pytest.raises(ValueError):
        oslo_date(datetime(2026, 1, 1))


@pytest.mark.parametrize("net,rate,expected", [(10000, 2500, 2500), (2, 2500, 1), (1, 2500, 0),
                                               (-2, 2500, -1), (333, 1200, 40), (0, 2500, 0)])
def test_vat_amount(net, rate, expected):
    assert vat_amount(net, rate) == expected


def test_orgnr_mod11():
    assert valid_orgnr("923609016")
    assert not valid_orgnr("923609017")
    assert not valid_orgnr("12345678")


def test_sniff():
    assert sniff_mime(b"%PDF-1.7 ...") == "application/pdf"
    assert sniff_mime(b"\x89PNG\r\n\x1a\nxxxx") == "image/png"
    assert sniff_mime(b"MZ\x90") is None


def test_format_nok():
    assert format_nok(-1234567) == "-12 345,67"
