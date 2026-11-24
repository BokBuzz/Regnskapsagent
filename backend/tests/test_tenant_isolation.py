"""En bruker kan aldri se eller endre et annet selskaps data, på noen rute.
Testen går gjennom alle registrerte ruter automatisk, så nye ruter dekkes."""

from __future__ import annotations

import re
import uuid

import pytest
from conftest import auth, create_company, fake_jpeg, post_manual, simple_draft


def _company_routes(client):
    # OpenAPI-beskrivelsen lister alle ruter, også de i inkluderte routere.
    for path, methods in client.app.openapi()["paths"].items():
        if "{company_id}" in path:
            for method in methods:
                yield method.upper(), path


def test_every_company_route_is_covered(client):
    assert len(list(_company_routes(client))) >= 15


def test_other_user_gets_404_on_every_company_route(client, app_db, user):
    victim = create_company(app_db, user, year=2026)
    posted = post_manual(app_db, victim, user, simple_draft())
    doc = client.post(f"/companies/{victim}/documents",
                      files={"file": ("a.jpg", fake_jpeg("v"), "image/jpeg")}, headers=auth(user)).json()
    real_ids = {"voucher_id": posted.id, "document_id": doc["id"], "proposal_id": uuid.uuid4(),
                "year": 2026, "month": 3, "match_id": uuid.uuid4(), "term": 1}
    attacker = uuid.uuid4()
    create_company(app_db, attacker)  # angriperen har et eget selskap

    checked = 0
    for method, path in _company_routes(client):
        url = path.replace("{company_id}", str(victim))
        url = re.sub(r"\{(\w+)\}", lambda m: str(real_ids[m.group(1)]), url)
        kwargs = {"headers": auth(attacker)}
        if method == "POST" and (url.endswith("/documents") or url.endswith("/bank/statements")):
            kwargs["files"] = {"file": ("b.jpg", fake_jpeg("att"), "image/jpeg")}
        elif method == "POST":
            kwargs["json"] = {"reason": "angrep", "confirm": True, "review_token": "x" * 20, "accept": True}
        if url.endswith("trial-balance"):
            url += "?from=2026-01-01&to=2026-12-31"
        r = client.request(method, url, **kwargs)
        assert r.status_code == 404, f"{method} {path} ga {r.status_code}: {r.text}"
        checked += 1
    assert checked >= 15

    # Og ingenting ble endret i offerets selskap.
    with app_db.tx(user) as conn:
        assert conn.execute("select count(*) n from bokbuzz.vouchers where company_id = %s",
                            [victim]).fetchone()["n"] == 1
        assert conn.execute("select count(*) n from bokbuzz.documents where company_id = %s",
                            [victim]).fetchone()["n"] == 1


@pytest.mark.parametrize("path", ["/companies/{other}/documents/{doc}", "/companies/{mine}/documents/{doc}"])
def test_cannot_reach_other_company_document_via_own_company(client, app_db, user, path):
    victim = create_company(app_db, user)
    doc = client.post(f"/companies/{victim}/documents",
                      files={"file": ("a.jpg", fake_jpeg("w"), "image/jpeg")}, headers=auth(user)).json()
    attacker = uuid.uuid4()
    mine = create_company(app_db, attacker)
    url = path.format(other=victim, mine=mine, doc=doc["id"])
    for suffix in ("", "/content"):
        assert client.get(url + suffix, headers=auth(attacker)).status_code == 404
