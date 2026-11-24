"""ENK og AS: kontoplan etter selskapsform, valgfrie moduler og «betalt privat»."""

from __future__ import annotations

from conftest import auth, create_company, random_orgnr
from test_proposals import receipt, run_jobs, upload

from bokbuzz.ai.base import ModelRouter
from bokbuzz.ai.fake import FakeModel
from bokbuzz.proposals.prompt import build_prompt


def _accounts(client, company, user) -> set[str]:
    return {a["number"] for a in client.get(f"/companies/{company}/accounts", headers=auth(user)).json()}


def test_create_as_via_api_gets_as_chart(client, user):
    r = client.post("/companies", headers=auth(user),
                    json={"orgnr": random_orgnr(), "name": "Test AS", "org_form": "AS"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["org_form"] == "AS" and body["modules"] == []
    acc = _accounts(client, body["id"], user)
    assert {"2000", "2910", "8300", "3000", "4000", "5000"} <= acc
    assert "2070" not in acc and "6790" not in acc  # ikke privat innskudd, ikke taxi


def test_enk_with_and_without_taxi_module(client, user):
    plain = client.post("/companies", headers=auth(user),
                        json={"orgnr": random_orgnr(), "name": "Frisør Hansen", "org_form": "ENK"}).json()
    taxi = client.post("/companies", headers=auth(user),
                       json={"orgnr": random_orgnr(), "name": "Ola Taxi", "org_form": "ENK",
                             "modules": ["taxi"]}).json()
    assert "2070" in _accounts(client, plain["id"], user)
    assert "6790" not in _accounts(client, plain["id"], user)
    assert {"6790", "1570", "3010"} <= _accounts(client, taxi["id"], user)


def test_unsupported_org_form_and_module_rejected(client, user):
    for extra in ({"org_form": "NUF"}, {"org_form": "ENK", "modules": ["fisk"]}):
        r = client.post("/companies", headers=auth(user),
                        json={"orgnr": random_orgnr(), "name": "X", **extra})
        assert r.status_code == 422


def test_paid_privately_goes_to_shareholder_debt_in_as(client, app_db, worker_db, storage, user):
    company = create_company(app_db, user, org_form="AS", modules=())
    upload(client, company, user)
    ex = receipt(payment="private")
    run_jobs(worker_db, storage, ModelRouter(FakeModel("a", ex), FakeModel("b", ex)), company)
    prop = client.get(f"/companies/{company}/proposals", headers=auth(user)).json()[0]
    accounts = [ln["account"] for ln in prop["draft"]["lines"]]
    assert "2910" in accounts and "2070" not in accounts


def test_prompt_names_org_form_and_modules():
    p = build_prompt([], [], org_form="AS")
    assert "aksjeselskap" in p
    assert "drosje" in build_prompt([], [], org_form="ENK", modules=["taxi"])
