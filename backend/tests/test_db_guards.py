"""Databasen som siste forsvarslinje: også direkte SQL skal stoppes."""

from __future__ import annotations

import uuid
from datetime import date

import psycopg
import pytest
from conftest import create_company, post_manual, simple_draft

from bokbuzz.ledger import service as ledger


def _approval(app_db, company, user):
    with app_db.tx(user) as conn:
        return ledger.create_approval(conn, company_id=company, actor=user, kind="manual",
                                      request=simple_draft())


def test_unbalanced_insert_is_rejected_at_commit(app_db, company, user):
    approval = _approval(app_db, company, user)
    with pytest.raises(psycopg.errors.CheckViolation), app_db.tx(user) as conn:
        vid = conn.execute(
            "insert into bokbuzz.vouchers (company_id, year, series, number, voucher_date, description,"
            " idempotency_key, content_hash, approval_id, posted_by, line_count)"
            " values (%s, 2026, 'B', 900, '2026-03-01', 'x', 'raw', 'h', %s, %s, 2) returning id",
            [company, approval, user]).fetchone()["id"]
        conn.execute("insert into bokbuzz.voucher_lines (voucher_id, company_id, line_no, account_number,"
                     " amount_ore) values (%s, %s, 1, '7000', 100), (%s, %s, 2, '1920', -99)",
                     [vid, company, vid, company])


def test_lines_cannot_be_added_to_posted_voucher(app_db, company, user):
    posted = post_manual(app_db, company, user, simple_draft())
    with pytest.raises(psycopg.errors.CheckViolation), app_db.tx(user) as conn:
        conn.execute("insert into bokbuzz.voucher_lines (voucher_id, company_id, line_no, account_number,"
                     " amount_ore) values (%s, %s, 10, '7000', 100), (%s, %s, 11, '1920', -100)",
                     [posted.id, company, posted.id, company])


@pytest.mark.parametrize("statement", [
    "update bokbuzz.vouchers set description = 'endret' where id = %s",
    "delete from bokbuzz.voucher_lines where voucher_id = %s",
    "update bokbuzz.voucher_lines set amount_ore = 1 where voucher_id = %s",
])
def test_posted_voucher_is_immutable_even_for_superuser(app_db, company, user, admin, statement):
    posted = post_manual(app_db, company, user, simple_draft())
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute(statement, [posted.id])


@pytest.mark.parametrize("table", ["vouchers", "voucher_lines", "audit_events", "documents"])
def test_truncate_is_blocked_even_for_superuser(admin, table):
    with pytest.raises(psycopg.Error):
        admin.execute(f"truncate bokbuzz.{table} cascade")


def test_app_role_has_no_delete_privilege(app_db, company, user):
    with pytest.raises(psycopg.errors.InsufficientPrivilege), app_db.tx(user) as conn:
        conn.execute("delete from bokbuzz.documents where company_id = %s", [company])


def test_closed_period_blocks_direct_insert(app_db, company, user, admin):
    with app_db.tx(user) as conn:
        ledger.close_period(conn, company_id=company, actor=user, year=2026, month=2)
    approval = _approval(app_db, company, user)
    with pytest.raises(psycopg.errors.RaiseException) as exc:
        admin.execute(
            "insert into bokbuzz.vouchers (company_id, year, series, number, voucher_date, description,"
            " idempotency_key, content_hash, approval_id, posted_by, line_count)"
            " values (%s, 2026, 'B', 901, '2026-02-10', 'x', 'raw2', 'h', %s, %s, 2)",
            [company, approval, user])
    assert exc.value.diag.message_hint == "period_closed"


def test_closed_period_cannot_be_reopened(app_db, company, user, admin):
    with app_db.tx(user) as conn:
        ledger.close_period(conn, company_id=company, actor=user, year=2026, month=1)
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("update bokbuzz.periods set status = 'open', closed_at = null"
                      " where company_id = %s and year = 2026 and month = 1", [company])


def test_rls_hides_other_companies(app_db, user):
    other_user = uuid.uuid4()
    mine = create_company(app_db, user)
    theirs = create_company(app_db, other_user)
    post_manual(app_db, theirs, other_user, simple_draft(on=date(2026, 5, 1)))
    with app_db.tx(user) as conn:
        assert conn.execute("select count(*) n from bokbuzz.vouchers where company_id = %s",
                            [theirs]).fetchone()["n"] == 0
        assert conn.execute("select count(*) n from bokbuzz.companies where id = %s",
                            [theirs]).fetchone()["n"] == 0
        ids = {r["id"] for r in conn.execute("select id from bokbuzz.companies").fetchall()}
        assert ids == {mine}


def test_rls_blocks_inserting_into_other_company(app_db, user):
    other_user = uuid.uuid4()
    theirs = create_company(app_db, other_user)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), app_db.tx(user) as conn:
        conn.execute("insert into bokbuzz.jobs (company_id, kind) values (%s, 'x')", [theirs])


def test_document_status_cannot_skip_steps(app_db, company, user, admin):
    import hashlib
    sha = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    with app_db.tx(user) as conn:
        doc = conn.execute(
            "insert into bokbuzz.documents (company_id, sha256, mime_type, size_bytes, storage_key, uploaded_by)"
            " values (%s, %s, 'image/jpeg', 10, 'k', %s) returning id", [company, sha, user]).fetchone()["id"]
    with pytest.raises(psycopg.errors.RaiseException), app_db.tx(user) as conn:
        conn.execute("update bokbuzz.documents set status = 'posted' where id = %s", [doc])
