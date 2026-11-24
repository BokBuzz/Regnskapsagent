"""Selvbetjening: /me, oppslag i Enhetsregisteret, forslagsdetaljer og CORS."""

from __future__ import annotations

import httpx
import pytest
from conftest import auth
from test_proposals import receipt, run_jobs, upload

from bokbuzz import brreg
from bokbuzz.ai.base import ModelRouter
from bokbuzz.ai.fake import FakeModel
from bokbuzz.errors import NotFound


def _client(status: int, body: dict | None = None) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body or {})))


def test_brreg_lookup_parses_enk():
    body = {"organisasjonsnummer": "923609016", "navn": "OLA NORDMANN TAXI",
            "organisasjonsform": {"kode": "ENK"}, "registrertIMvaregisteret": True,
            "forretningsadresse": {"adresse": ["Gate 1"], "postnummer": "7010", "poststed": "TRONDHEIM"}}
    e = brreg.lookup("923609016", "https://x", client=_client(200, body))
    assert (e.name, e.org_form, e.vat_registered, e.deleted) == ("OLA NORDMANN TAXI", "ENK", True, False)
    assert e.address == "Gate 1, 7010, TRONDHEIM"


def test_brreg_not_found_and_unavailable():
    with pytest.raises(NotFound):
        brreg.lookup("923609016", "https://x", client=_client(404))
    with pytest.raises(brreg.LookupUnavailable):
        brreg.lookup("923609016", "https://x", client=_client(500))


def test_me_and_invalid_orgnr_lookup(client, user):
    assert client.get("/me", headers=auth(user)).json()["user_id"] == str(user)
    assert client.get("/lookup/orgnr/123456789", headers=auth(user)).status_code == 422


def test_proposal_detail_includes_document(client, app_db, worker_db, storage, company, user):
    doc = upload(client, company, user)
    run_jobs(worker_db, storage, ModelRouter(FakeModel("a", receipt()), FakeModel("b", receipt())), company)
    pid = client.get(f"/companies/{company}/proposals", headers=auth(user)).json()[0]["id"]
    r = client.get(f"/companies/{company}/proposals/{pid}", headers=auth(user))
    assert r.status_code == 200 and r.json()["document"]["id"] == doc


def test_cors_allows_only_configured_origin(client):
    ok = client.options("/companies", headers={"origin": "http://localhost:5173",
                                                "access-control-request-method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/companies", headers={"origin": "https://evil.example",
                                                 "access-control-request-method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_vat_codes_on_date(client, user):
    codes = {c["code"]: c["rate_bp"] for c in client.get("/vat-codes?on=2021-05-01", headers=auth(user)).json()}
    assert codes["1"] == 2500 and codes["33"] == 600
    assert client.get("/vat-codes").status_code == 401
