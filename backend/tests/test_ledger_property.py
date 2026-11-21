"""Egenskapsbasert test: tilfeldige godkjente bilag holder alltid saldobalansen i null."""

from __future__ import annotations

from datetime import date

from conftest import post_manual
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bokbuzz.ledger import service as ledger
from bokbuzz.ledger.models import DraftLine, VoucherDraft
from bokbuzz.ledger.money import vat_amount

EXPENSES = ["6540", "6800", "6900", "7000", "7020", "7090", "7790"]
VAT_CODES = {None: 0, "1": 2500, "11": 1500, "13": 1200}


@st.composite
def purchase(draw) -> VoucherDraft:
    n = draw(st.integers(min_value=1, max_value=5))
    lines, total = [], 0
    for _ in range(n):
        net = draw(st.integers(min_value=1, max_value=5_000_000))
        code = draw(st.sampled_from(list(VAT_CODES)))
        account = draw(st.sampled_from(EXPENSES))
        lines.append(DraftLine(account=account, amount_ore=net, vat_code=code))
        total += net + vat_amount(net, VAT_CODES[code])
    pay = draw(st.sampled_from(["1920", "2070", "2400", "1900"]))
    lines.append(DraftLine(account=pay, amount_ore=-total))
    day = draw(st.dates(min_value=date(2026, 1, 1), max_value=date(2026, 12, 31)))
    return VoucherDraft(voucher_date=day, description="Tilfeldig kjøp", lines=lines)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(drafts=st.lists(purchase(), min_size=1, max_size=4))
def test_trial_balance_is_always_zero(app_db, company, user, drafts):
    for d in drafts:
        post_manual(app_db, company, user, d)
    with app_db.tx(user) as conn:
        tb = ledger.trial_balance(conn, company, date(2026, 1, 1), date(2026, 12, 31))
    assert sum(r["balance_ore"] for r in tb) == 0


@given(net=st.integers(min_value=-10**12, max_value=10**12), rate=st.sampled_from([0, 600, 1200, 1500, 2500]))
def test_vat_rounding_is_symmetric_and_close(net, rate):
    v = vat_amount(net, rate)
    assert vat_amount(-net, rate) == -v
    assert abs(v * 10000 - net * rate) <= 5000
