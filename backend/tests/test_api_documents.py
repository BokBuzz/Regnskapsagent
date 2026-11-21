"""Innlogging og opplasting via API-et."""

from __future__ import annotations

import uuid

from conftest import auth, fake_jpeg


def test_requires_login(client):
    assert client.get("/companies").status_code == 401
    assert client.get("/companies", headers={"authorization": "Bearer tull"}).status_code == 401


def test_requires_mfa(client, user):
    r = client.get("/companies", headers=auth(user, aal="aal1"))
    assert r.status_code == 403 and r.json()["detail"]["error"] == "mfa_required"


def test_create_company_makes_owner_with_chart_and_periods(client, user):
    r = client.post("/companies", json={"orgnr": "923 609 016", "name": "Ola Taxi"}, headers=auth(user))
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    accounts = client.get(f"/companies/{cid}/accounts", headers=auth(user)).json()
    assert {"1920", "2710", "7000"} <= {a["number"] for a in accounts}
    periods = client.get(f"/companies/{cid}/periods", headers=auth(user)).json()
    assert len(periods) == 12 and all(p["status"] == "open" for p in periods)
    assert client.get(f"/companies/{cid}/audit/verify", headers=auth(user)).json() == {"ok": True}


def test_invalid_orgnr_is_rejected(client, user):
    r = client.post("/companies", json={"orgnr": "123456789", "name": "x"}, headers=auth(user))
    assert r.status_code == 422


def test_upload_dedupes_same_file(client, company, user, storage):
    files = {"file": ("kvittering.jpg", fake_jpeg("dup"), "image/jpeg")}
    first = client.post(f"/companies/{company}/documents", files=files, headers=auth(user))
    assert first.status_code == 201, first.text
    second = client.post(f"/companies/{company}/documents", files=files, headers=auth(user))
    assert second.status_code == 200 and second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]
    docs = client.get(f"/companies/{company}/documents", headers=auth(user)).json()
    assert len(docs) == 1
    content = client.get(f"/companies/{company}/documents/{first.json()['id']}/content", headers=auth(user))
    assert content.content == fake_jpeg("dup")


def test_upload_rejects_wrong_type_even_with_jpeg_name(client, company, user):
    files = {"file": ("kvittering.jpg", b"MZ\x90\x00 dette er en exe", "image/jpeg")}
    r = client.post(f"/companies/{company}/documents", files=files, headers=auth(user))
    assert r.status_code == 422 and r.json()["error"] == "unsupported_type"


def test_upload_rejects_too_large(client, company, user):
    files = {"file": ("stor.jpg", fake_jpeg("x") * 5000, "image/jpeg")}
    r = client.post(f"/companies/{company}/documents", files=files, headers=auth(user))
    assert r.status_code == 422 and r.json()["error"] == "file_too_large"


def test_upload_enqueues_extraction_job(client, company, user, app_db):
    r = client.post(f"/companies/{company}/documents",
                    files={"file": ("a.jpg", fake_jpeg("job"), "image/jpeg")}, headers=auth(user))
    with app_db.tx(user) as conn:
        job = conn.execute("select * from bokbuzz.jobs where company_id = %s", [company]).fetchone()
    assert job["kind"] == "extract_document" and job["payload"]["document_id"] == r.json()["id"]


def test_reader_cannot_upload(client, company, admin):
    from conftest import add_member
    reader = uuid.uuid4()
    add_member(admin, company, reader, "reader")
    r = client.post(f"/companies/{company}/documents",
                    files={"file": ("a.jpg", fake_jpeg("r"), "image/jpeg")}, headers=auth(reader))
    assert r.status_code == 403
