"""Hovedboken: post_voucher, MVA, idempotens, perioder og reversering."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from conftest import create_company, post_manual, simple_draft

from bokbuzz.errors import Conflict, Forbidden, ValidationFailed
from bokbuzz.ledger import service as ledger
from bokbuzz.ledger.models import DraftLine, VoucherDraft


def test_post_simple_voucher_with_vat_line(app_db, company, user):
    posted = post_manual(app_db, company, user, simple_draft(10000))
    assert (posted.series, posted.number, posted.year) == ("B", 1, 2026)
    assert [(ln.account, ln.amount_ore, ln.vat_code) for ln in posted.lines] == [
        ("7000", 10000, "1"), ("2710", 2500, "1"), ("1920", -12500, None)]
    assert posted.lines[1].vat_base_line_no == 1


def test_numbers_are_sequential_per_series_and_year(app_db, company, user):
    numbers = [post_manual(app_db, company, user, simple_draft(100 * (i + 1))).number for i in range(5)]
    assert numbers == [1, 2, 3, 4, 5]


def test_unbalanced_is_rejected_and_number_is_not_consumed(app_db, company, user):
    bad = VoucherDraft(voucher_date=date(2026, 3, 1), description="Feil", lines=[
        DraftLine(account="7000", amount_ore=10000, vat_code="1"),
        DraftLine(account="1920", amount_ore=-10000)])
    with pytest.raises(ValidationFailed) as exc:
        post_manual(app_db, company, user, bad)
    assert exc.value.code == "unbalanced"
    assert post_manual(app_db, company, user, simple_draft()).number == 1


def test_vat_explicit_within_tolerance_is_used(app_db, company, user):
    draft = VoucherDraft(voucher_date=date(2026, 3, 1), description="Bom", lines=[
        DraftLine(account="7090", amount_ore=1999, vat_code="1", vat_amount_ore=499),
        DraftLine(account="1920", amount_ore=-2498)])
    posted = post_manual(app_db, company, user, draft)
    assert posted.lines[1].amount_ore == 499  # beregnet 500, oppgitt 499 (innen 1 øre)


def test_vat_explicit_outside_tolerance_is_rejected(app_db, company, user):
    draft = VoucherDraft(voucher_date=date(2026, 3, 1), description="Bom", lines=[
        DraftLine(account="7090", amount_ore=2000, vat_code="1", vat_amount_ore=480),
        DraftLine(account="1920", amount_ore=-2480)])
    with pytest.raises(ValidationFailed) as exc:
        post_manual(app_db, company, user, draft)
    assert exc.value.code == "vat_mismatch"


def test_low_rate_uses_rate_valid_on_voucher_date(app_db, user):
    company = create_company(app_db, user, year=2021)
    draft = VoucherDraft(voucher_date=date(2021, 5, 1), description="Taxitur", lines=[
        DraftLine(account="1920", amount_ore=10600),
        DraftLine(account="3000", amount_ore=-10000, vat_code="33")])
    posted = post_manual(app_db, company, user, draft)
    assert [ln.amount_ore for ln in posted.lines] == [10600, -10000, -600]  # 6 % i 2021 (verifiser)


def test_unknown_account_is_rejected(app_db, company, user):
    draft = VoucherDraft(voucher_date=date(2026, 3, 1), description="x", lines=[
        DraftLine(account="9999", amount_ore=100), DraftLine(account="1920", amount_ore=-100)])
    with pytest.raises(ValidationFailed) as exc:
        post_manual(app_db, company, user, draft)
    assert exc.value.code == "inactive_account"


def test_idempotency_same_content_returns_same_voucher(app_db, company, user):
    draft = simple_draft()
    first = post_manual(app_db, company, user, draft, key="k1")
    second = post_manual(app_db, company, user, draft, key="k1")
    assert second.id == first.id and second.created is False
    with app_db.tx(user) as conn:
        n = conn.execute("select count(*) n from bokbuzz.vouchers where company_id = %s", [company]).fetchone()
    assert n["n"] == 1


def test_idempotency_other_content_is_rejected(app_db, company, user):
    post_manual(app_db, company, user, simple_draft(100), key="k2")
    with pytest.raises(Conflict) as exc:
        post_manual(app_db, company, user, simple_draft(200), key="k2")
    assert exc.value.code == "idempotency_conflict"


def test_closed_period_is_rejected(app_db, company, user):
    with app_db.tx(user) as conn:
        ledger.close_period(conn, company_id=company, actor=user, year=2026, month=3)
    with pytest.raises(Conflict) as exc:
        post_manual(app_db, company, user, simple_draft(on=date(2026, 3, 31)))
    assert exc.value.code == "period_closed"
    post_manual(app_db, company, user, simple_draft(on=date(2026, 4, 1)))


def test_period_without_open_year_is_rejected(app_db, company, user):
    with pytest.raises(Conflict):
        post_manual(app_db, company, user, simple_draft(on=date(2019, 1, 1)))


def test_reader_cannot_post(app_db, company, user, admin):
    from conftest import add_member
    reader = uuid.uuid4()
    add_member(admin, company, reader, "reader")
    with pytest.raises(Forbidden):
        post_manual(app_db, company, reader, simple_draft())


def test_approval_must_match_content(app_db, company, user):
    with app_db.tx(user) as conn:
        approval = ledger.create_approval(conn, company_id=company, actor=user, kind="manual",
                                          request=simple_draft(100))
    with pytest.raises(Conflict) as exc, app_db.tx(user) as conn:
        ledger.post_voucher(conn, company_id=company, actor=user, request=simple_draft(200),
                            approval_id=approval, idempotency_key="x")
    assert exc.value.code == "approval_mismatch"


def test_approval_cannot_be_reused(app_db, company, user):
    draft = simple_draft()
    with app_db.tx(user) as conn:
        approval = ledger.create_approval(conn, company_id=company, actor=user, kind="manual", request=draft)
        ledger.post_voucher(conn, company_id=company, actor=user, request=draft, approval_id=approval,
                            idempotency_key="a")
    with pytest.raises(Conflict) as exc, app_db.tx(user) as conn:
        ledger.post_voucher(conn, company_id=company, actor=user, request=draft, approval_id=approval,
                            idempotency_key="b")
    assert exc.value.code == "approval_used"


def test_approval_from_other_user_is_rejected(app_db, company, user, admin):
    from conftest import add_member
    other = uuid.uuid4()
    add_member(admin, company, other, "accountant")
    draft = simple_draft()
    with app_db.tx(user) as conn:
        approval = ledger.create_approval(conn, company_id=company, actor=user, kind="manual", request=draft)
    with pytest.raises(Forbidden), app_db.tx(other) as conn:
        ledger.post_voucher(conn, company_id=company, actor=other, request=draft, approval_id=approval,
                            idempotency_key="c")


def test_reversal_nets_to_zero_and_only_once(app_db, company, user):
    posted = post_manual(app_db, company, user, simple_draft(10000))
    with app_db.tx(user) as conn:
        rev = ledger.reverse_voucher(conn, company_id=company, actor=user, voucher_id=posted.id,
                                     reason="Feil konto", voucher_date=date(2026, 3, 20))
    assert rev.series == "R" and rev.reverses_voucher_id == posted.id
    with app_db.tx(user) as conn:
        tb = ledger.trial_balance(conn, company, date(2026, 1, 1), date(2026, 12, 31))
        assert all(r["balance_ore"] == 0 for r in tb)
        with pytest.raises(Conflict):
            ledger.reverse_voucher(conn, company_id=company, actor=user, voucher_id=posted.id,
                                   reason="Igjen", voucher_date=date(2026, 3, 21))


def test_trial_balance_sums_to_zero(app_db, company, user):
    for amount in (1000, 2345, 99999):
        post_manual(app_db, company, user, simple_draft(amount))
    with app_db.tx(user) as conn:
        tb = ledger.trial_balance(conn, company, date(2026, 1, 1), date(2026, 12, 31))
    assert sum(r["balance_ore"] for r in tb) == 0
    assert {r["account"] for r in tb} == {"7000", "2710", "1920"}
