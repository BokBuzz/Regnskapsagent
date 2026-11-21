"""Godkjenning krever minst to klikk: åpne til gjennomgang, deretter bekrefte."""

from __future__ import annotations

import uuid

from conftest import add_member, auth
from test_proposals import receipt, run_jobs, upload

from bokbuzz.ai.base import ModelRouter
from bokbuzz.ai.fake import FakeModel


def pending_proposal(client, app_db, worker_db, storage, company, user, ex=None) -> str:
    upload(client, company, user, seed=uuid.uuid4().hex)
    ex = ex or receipt()
    run_jobs(worker_db, storage, ModelRouter(FakeModel("a", ex), FakeModel("b", ex)), company)
    props = client.get(f"/companies/{company}/proposals?status=all", headers=auth(user)).json()
    return props[-1]["id"]


def base(company, pid):
    return f"/companies/{company}/proposals/{pid}"


def test_one_click_approval_is_impossible(client, app_db, worker_db, storage, company, user):
    pid = pending_proposal(client, app_db, worker_db, storage, company, user)
    r = client.post(base(company, pid) + "/approve", json={"confirm": True, "review_token": "x" * 32},
                    headers=auth(user))
    assert r.status_code == 403 and r.json()["error"] == "review_required"
    r = client.post(base(company, pid) + "/approve", json={"review_token": "x" * 32}, headers=auth(user))
    assert r.status_code == 422  # confirm mangler


def test_two_clicks_post_the_voucher(client, app_db, worker_db, storage, company, user):
    pid = pending_proposal(client, app_db, worker_db, storage, company, user)
    click1 = client.post(base(company, pid) + "/review", headers=auth(user))
    assert click1.status_code == 200, click1.text
    token = click1.json()["review_token"]
    click2 = client.post(base(company, pid) + "/approve", json={"confirm": True, "review_token": token},
                         headers=auth(user))
    assert click2.status_code == 200, click2.text
    v = click2.json()
    assert v["number"] == 1 and sum(ln["amount_ore"] for ln in v["lines"]) == 0
    assert [ln["account"] for ln in v["lines"]] == ["7000", "2710", "1920"]
    doc = client.get(f"/companies/{company}/documents/{v['document_id']}", headers=auth(user)).json()
    assert doc["status"] == "posted"
    # Samme token kan ikke brukes igjen.
    again = client.post(base(company, pid) + "/approve", json={"confirm": True, "review_token": token},
                        headers=auth(user))
    assert again.status_code == 409
    assert client.get(f"/companies/{company}/audit/verify", headers=auth(user)).json() == {"ok": True}


def test_token_is_personal(client, app_db, worker_db, storage, company, user, admin):
    pid = pending_proposal(client, app_db, worker_db, storage, company, user)
    colleague = uuid.uuid4()
    add_member(admin, company, colleague, "accountant")
    token = client.post(base(company, pid) + "/review", headers=auth(user)).json()["review_token"]
    r = client.post(base(company, pid) + "/approve", json={"confirm": True, "review_token": token},
                    headers=auth(colleague))
    assert r.status_code == 403


def test_reader_cannot_review_or_approve(client, app_db, worker_db, storage, company, user, admin):
    pid = pending_proposal(client, app_db, worker_db, storage, company, user)
    reader = uuid.uuid4()
    add_member(admin, company, reader, "reader")
    assert client.post(base(company, pid) + "/review", headers=auth(reader)).status_code == 403


def test_corrected_draft_is_posted_and_marked(client, app_db, worker_db, storage, company, user):
    pid = pending_proposal(client, app_db, worker_db, storage, company, user)
    token = client.post(base(company, pid) + "/review", headers=auth(user)).json()["review_token"]
    corrected = {"voucher_date": "2026-03-10", "description": "Vask av bil", "lines": [
        {"account": "7090", "amount_ore": 50000, "vat_code": "1"},
        {"account": "2070", "amount_ore": -62500}]}
    r = client.post(base(company, pid) + "/approve",
                    json={"confirm": True, "review_token": token, "corrected_draft": corrected},
                    headers=auth(user))
    assert r.status_code == 200, r.text
    assert [ln["account"] for ln in r.json()["lines"]] == ["7090", "2710", "2070"]
    p = client.get(f"/companies/{company}/proposals?status=approved", headers=auth(user)).json()[0]
    assert p["decision_note"] == "rettet av bruker"


def test_needs_manual_requires_corrected_draft(client, app_db, worker_db, storage, company, user):
    pid = pending_proposal(client, app_db, worker_db, storage, company, user, ex=receipt(document_date=None))
    token = client.post(base(company, pid) + "/review", headers=auth(user)).json()["review_token"]
    r = client.post(base(company, pid) + "/approve", json={"confirm": True, "review_token": token},
                    headers=auth(user))
    assert r.status_code == 422 and r.json()["error"] == "draft_required"


def test_rules_change_invalidates_proposal(client, app_db, worker_db, storage, company, user, admin):
    pid = pending_proposal(client, app_db, worker_db, storage, company, user)
    token = client.post(base(company, pid) + "/review", headers=auth(user)).json()["review_token"]
    admin.execute("update bokbuzz.accounts set active_to = '2030-12-31' where company_id = %s"
                  " and number = '6800'", [company])
    r = client.post(base(company, pid) + "/approve", json={"confirm": True, "review_token": token},
                    headers=auth(user))
    assert r.status_code == 409 and r.json()["error"] == "rules_changed"


def test_reject_and_reverse(client, app_db, worker_db, storage, company, user):
    pid = pending_proposal(client, app_db, worker_db, storage, company, user)
    r = client.post(base(company, pid) + "/reject", json={"reason": "Privat kjøp"}, headers=auth(user))
    assert r.status_code == 200 and r.json()["status"] == "rejected"

    pid2 = pending_proposal(client, app_db, worker_db, storage, company, user)
    token = client.post(base(company, pid2) + "/review", headers=auth(user)).json()["review_token"]
    v = client.post(base(company, pid2) + "/approve", json={"confirm": True, "review_token": token},
                    headers=auth(user)).json()
    rev = client.post(f"/companies/{company}/vouchers/{v['id']}/reverse",
                      json={"reason": "Feil leverandør", "confirm": True, "voucher_date": "2026-03-31"},
                      headers=auth(user))
    assert rev.status_code == 201, rev.text
    tb = client.get(f"/companies/{company}/reports/trial-balance?from=2026-01-01&to=2026-12-31",
                    headers=auth(user)).json()
    assert tb["total_ore"] == 0 and all(a["balance_ore"] == 0 for a in tb["accounts"])


def test_document_cannot_be_posted_outside_its_proposal(app_db, worker_db, client, storage, company, user):
    """Ingen kodevei bokfører et dokument uten forslag + gjennomgang."""
    import pytest

    from bokbuzz.errors import Forbidden
    from bokbuzz.ledger import service as ledger
    from bokbuzz.ledger.models import DraftLine, VoucherDraft

    doc = upload(client, company, user, seed="direkte")
    draft = VoucherDraft(voucher_date="2026-03-10", description="x", lines=[
        DraftLine(account="7000", amount_ore=100), DraftLine(account="1920", amount_ore=-100)])
    with pytest.raises(Forbidden), app_db.tx(user) as conn:
        approval = ledger.create_approval(conn, company_id=company, actor=user, kind="manual", request=draft)
        ledger.post_voucher(conn, company_id=company, actor=user, request=draft, approval_id=approval,
                            idempotency_key="direct", document_id=doc)
