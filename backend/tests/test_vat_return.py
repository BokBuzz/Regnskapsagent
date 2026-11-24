"""MVA-melding: beregning per termin, kontroller og XML. Innsending er ikke koblet på ennå."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import auth, post_manual, simple_draft
from defusedxml import ElementTree as ET

from bokbuzz.ledger.models import DraftLine, VoucherDraft
from bokbuzz.vat.return_draft import XML_NS, Term


def sale(net_ore: int, on: date) -> VoucherDraft:
    """Salg med 25 % MVA, betalt til bank."""
    return VoucherDraft(voucher_date=on, description="Salg", lines=[
        DraftLine(account="3600", amount_ore=-net_ore, vat_code="3"),
        DraftLine(account="1920", amount_ore=net_ore + net_ore // 4),
    ])


@pytest.mark.parametrize("term,start,end,due", [
    (1, date(2026, 1, 1), date(2026, 2, 28), date(2026, 4, 10)),
    (2, date(2026, 3, 1), date(2026, 4, 30), date(2026, 6, 10)),
    (3, date(2026, 5, 1), date(2026, 6, 30), date(2026, 8, 31)),
    (6, date(2026, 11, 1), date(2026, 12, 31), date(2027, 2, 10)),
])
def test_bimonthly_terms(term, start, end, due):
    t = Term(2026, term, "bimonthly")
    assert (t.start, t.end, t.due) == (start, end, due)


def test_annual_term():
    t = Term(2026, 1, "annual")
    assert (t.start, t.end, t.due) == (date(2026, 1, 1), date(2026, 12, 31), date(2027, 3, 10))


def test_vat_return_sums_output_and_input_per_code(client, app_db, company, user):
    post_manual(app_db, company, user, sale(100_000, date(2026, 3, 5)))         # 1000 kr + 250 MVA
    post_manual(app_db, company, user, simple_draft(50_000, date(2026, 4, 2)))  # kjøp 500 kr + 125 MVA
    post_manual(app_db, company, user, simple_draft(10_000, date(2026, 5, 2)))  # neste termin
    r = client.get(f"/companies/{company}/vat-returns/2026/2", headers=auth(user))
    assert r.status_code == 200, r.text
    d = r.json()
    lines = {ln["code"]: (ln["base_ore"], ln["vat_ore"]) for ln in d["lines"]}
    assert lines == {"1": (-50_000, -12_500), "3": (100_000, 25_000)}
    assert d["total_ore"] == 12_500 and d["result"] == "to_pay"
    assert d["label"] == "mars-april 2026" and d["due"] == "2026-06-10"
    assert d["submission_available"] is False
    codes = {c["code"] for c in d["checks"]}
    assert "bank_not_imported" in codes and "periods_open" in codes


def test_reversed_voucher_cancels_out(client, app_db, company, user):
    from bokbuzz.ledger import service as ledger

    v = post_manual(app_db, company, user, sale(100_000, date(2026, 3, 5)))
    with app_db.tx(user) as conn:
        ledger.reverse_voucher(conn, company_id=company, actor=user, voucher_id=v.id, reason="Feil",
                               voucher_date=date(2026, 3, 6))
    d = client.get(f"/companies/{company}/vat-returns/2026/2", headers=auth(user)).json()
    assert d["lines"] == [] and d["total_ore"] == 0 and d["result"] == "zero"


def test_pending_proposals_block_submission_check(client, app_db, worker_db, storage, company, user):
    from test_review_two_clicks import pending_proposal

    pending_proposal(client, app_db, worker_db, storage, company, user)  # kvittering datert 10.3.2026
    d = client.get(f"/companies/{company}/vat-returns/2026/2", headers=auth(user)).json()
    [check] = [c for c in d["checks"] if c["code"] == "pending_proposals"]
    assert check["severity"] == "error"


def test_invalid_term_and_non_vat_company(client, app_db, admin, company, user):
    assert client.get(f"/companies/{company}/vat-returns/2026/7", headers=auth(user)).status_code == 422
    admin.execute("update bokbuzz.companies set vat_registered = false where id = %s", [company])
    assert client.get(f"/companies/{company}/vat-returns/2026/1", headers=auth(user)).status_code == 422


def test_xml_has_expected_structure(client, app_db, company, user):
    post_manual(app_db, company, user, sale(100_000, date(2026, 3, 5)))
    post_manual(app_db, company, user, simple_draft(50_000, date(2026, 4, 2)))
    r = client.get(f"/companies/{company}/vat-returns/2026/2/xml", headers=auth(user))
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(r.content)
    ns = {"m": XML_NS}
    assert root.tag == f"{{{XML_NS}}}mvaMeldingDto"
    assert root.findtext("m:skattegrunnlagOgBeregnetSkatt/m:fastsattMerverdiavgift", namespaces=ns) == "125.00"
    assert root.findtext(".//m:skattleggingsperiodeToMaaneder", namespaces=ns) == "mars-april"
    specs = {s.findtext("m:mvaKode", namespaces=ns): s for s in root.iterfind(".//m:mvaSpesifikasjonslinje", ns)}
    assert specs["3"].findtext("m:grunnlag", namespaces=ns) == "1000.00"
    assert specs["3"].findtext("m:sats", namespaces=ns) == "25"
    assert specs["1"].findtext("m:merverdiavgift", namespaces=ns) == "-125.00"
    assert specs["1"].find("m:grunnlag", ns) is None
