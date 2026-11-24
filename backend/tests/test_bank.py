"""Bankagent v1: CAMT.053-import, avstemming mot hovedboken og forslag fra banklinjer."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import auth, post_manual, simple_draft

from bokbuzz import jobs
from bokbuzz.bank import rules
from bokbuzz.bank.camt import parse_camt053, to_ore
from bokbuzz.bank.service import reconcile_job
from bokbuzz.errors import ValidationFailed

ACCOUNT = "15030012345"


def entry(amount: str, ind: str, booked: str, *, ref: str | None = None, text: str | None = None,
          name: str | None = None, kid: str | None = None, code: tuple[str, str, str] | None = None,
          status: str = "BOOK", v8: bool = False) -> str:
    party = ""
    if name:
        role = "Cdtr" if ind == "DBIT" else "Dbtr"
        party = f"<RltdPties><{role}><Nm>{name}</Nm></{role}></RltdPties>"
    rmt = ""
    if kid or text:
        rmt = "<RmtInf>" + (f"<Ustrd>{text}</Ustrd>" if text else "") + (
            f"<Strd><CdtrRefInf><Ref>{kid}</Ref></CdtrRefInf></Strd>" if kid else "") + "</RmtInf>"
    bk = ""
    if code:
        bk = (f"<BkTxCd><Domn><Cd>{code[0]}</Cd><Fmly><Cd>{code[1]}</Cd><SubFmlyCd>{code[2]}</SubFmlyCd>"
              "</Fmly></Domn></BkTxCd>")
    sts = f"<Sts><Cd>{status}</Cd></Sts>" if v8 else f"<Sts>{status}</Sts>"
    return (f'<Ntry><Amt Ccy="NOK">{amount}</Amt><CdtDbtInd>{ind}</CdtDbtInd>{sts}'
            f"<BookgDt><Dt>{booked}</Dt></BookgDt><ValDt><Dt>{booked}</Dt></ValDt>"
            + (f"<AcctSvcrRef>{ref}</AcctSvcrRef>" if ref else "") + bk
            + f"<NtryDtls><TxDtls>{party}{rmt}</TxDtls></NtryDtls></Ntry>")


def camt(entries: list[str], *, opening: str | None = "10000.00", closing: str | None = None,
         frm: str = "2026-03-01", to: str = "2026-03-31", version: str = "02", stmt_id: str = "S1") -> bytes:
    bal = ""
    if opening is not None:
        bal += (f'<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="NOK">{opening}</Amt>'
                f"<CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{frm}</Dt></Dt></Bal>")
    if closing is not None:
        bal += (f'<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="NOK">{closing}</Amt>'
                f"<CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{to}</Dt></Dt></Bal>")
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
           f'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.{version}"><BkToCstmrStmt>'
           f"<GrpHdr><MsgId>M1</MsgId><CreDtTm>{to}T23:00:00</CreDtTm></GrpHdr>"
           f"<Stmt><Id>{stmt_id}</Id><CreDtTm>{to}T23:00:00</CreDtTm>"
           f"<FrToDt><FrDtTm>{frm}T00:00:00</FrDtTm><ToDtTm>{to}T23:59:59</ToDtTm></FrToDt>"
           f"<Acct><Id><Othr><Id>{ACCOUNT}</Id></Othr></Id><Ccy>NOK</Ccy></Acct>{bal}"
           + "".join(entries) + "</Stmt></BkToCstmrStmt></Document>")
    return xml.encode()


def upload(client, company, user, data: bytes, name: str = "utskrift.xml"):
    return client.post(f"/companies/{company}/bank/statements", files={"file": (name, data, "application/xml")},
                       headers=auth(user))


def run_reconcile(worker_db, company) -> None:
    while jobs.run_once(worker_db, {"bank_reconcile": reconcile_job()}, company_id=company):
        pass


def transactions(client, company, user, **params) -> list[dict]:
    r = client.get(f"/companies/{company}/bank/transactions", params=params, headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("version,v8", [("02", False), ("08", True)])
def test_parser_reads_amounts_signs_parties_and_only_booked(version, v8):
    data = camt([
        entry("625.00", "DBIT", "2026-03-12", ref="A1", name="Circle K", text="Varekjøp kort", v8=v8),
        entry("1250.50", "CRDT", "2026-03-13", ref="A2", name="Kunde AS", kid="0012345678", v8=v8),
        entry("99.00", "DBIT", "2026-03-14", ref="A3", status="PDNG", v8=v8),
    ], closing="10625.50", version=version)
    [stmt] = parse_camt053(data)
    assert stmt.account_id == ACCOUNT and stmt.currency == "NOK"
    assert [(e.amount_ore, e.counterparty_name) for e in stmt.entries] == [(-62500, "Circle K"),
                                                                           (125050, "Kunde AS")]
    assert stmt.entries[1].reference == "0012345678"
    assert stmt.opening_balance_ore == 1_000_000 and stmt.balance_ok is True
    assert stmt.from_date == date(2026, 3, 1) and stmt.to_date == date(2026, 3, 31)


def test_parser_detects_balance_mismatch():
    [stmt] = parse_camt053(camt([entry("1.00", "DBIT", "2026-03-02", ref="X")], closing="10000.00"))
    assert stmt.balance_ok is False


def test_amounts_never_use_floats():
    assert to_ore("0.1") == 10 and to_ore("1234567.89") == 123456789
    with pytest.raises(ValidationFailed):
        to_ore("1.005")


@pytest.mark.parametrize("data", [
    b"not xml",
    b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"/>',
    b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">&x;</Document>',
    b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
    b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">&b;</Document>',
])
def test_parser_rejects_wrong_files_and_entity_tricks(data):
    with pytest.raises(ValidationFailed):
        parse_camt053(data)


def test_identical_entries_without_bank_ref_get_distinct_stable_fingerprints():
    e = entry("50.00", "DBIT", "2026-03-05", text="Parkering")
    [a] = parse_camt053(camt([e, e]))
    [b] = parse_camt053(camt([e, e], stmt_id="S2"))
    assert len({x.fingerprint for x in a.entries}) == 2
    assert [x.fingerprint for x in a.entries] == [x.fingerprint for x in b.entries]


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
def test_import_is_idempotent_and_overlapping_statements_do_not_duplicate(client, company, user):
    first = camt([entry("100.00", "DBIT", "2026-03-02", ref="R1"), entry("200.00", "DBIT", "2026-03-20", ref="R2")])
    r = upload(client, company, user, first)
    assert r.status_code == 201, r.text
    assert r.json()["statements"][0]["new_count"] == 2
    assert upload(client, company, user, first).status_code == 200  # samme fil
    overlap = camt([entry("200.00", "DBIT", "2026-03-20", ref="R2"), entry("300.00", "DBIT", "2026-04-02", ref="R3")],
                   frm="2026-03-15", to="2026-04-15")
    r = upload(client, company, user, overlap)
    assert r.status_code == 201 and r.json()["statements"][0]["new_count"] == 1
    assert len(transactions(client, company, user)) == 3


def test_reader_role_cannot_import(client, app_db, admin, company):
    import uuid

    from conftest import add_member
    reader = uuid.uuid4()
    add_member(admin, company, reader, "reader")
    assert upload(client, company, reader, camt([])).status_code == 403


def test_bank_data_is_immutable(admin, client, company, user):
    upload(client, company, user, camt([entry("100.00", "DBIT", "2026-03-02", ref="I1")]))
    import psycopg
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("update bokbuzz.bank_transactions set amount_ore = 1 where company_id = %s", [company])
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("delete from bokbuzz.bank_statements where company_id = %s", [company])


# ---------------------------------------------------------------------------
# Avstemming
# ---------------------------------------------------------------------------
def test_posted_receipt_is_matched_and_user_confirms(client, app_db, worker_db, company, user):
    # Diesel 500 + 125 MVA = 625 kr, kvittering 10.3, trukket i banken 12.3.
    post_manual(app_db, company, user, simple_draft(50000, date(2026, 3, 10)))
    upload(client, company, user, camt([entry("625.00", "DBIT", "2026-03-12", ref="M1", name="Circle K")]))
    run_reconcile(worker_db, company)
    [tx] = transactions(client, company, user)
    assert tx["status"] == "suggested" and tx["match"]["method"] == "exact_unique"
    assert "eneste bilag" in tx["match"]["explanation"] and tx["voucher"]["series"] == "B"
    r = client.post(f"/companies/{company}/bank/matches/{tx['match']['id']}", json={"accept": True},
                    headers=auth(user))
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert transactions(client, company, user)[0]["status"] == "matched"
    # En bekreftet kobling kan ikke endres.
    r = client.post(f"/companies/{company}/bank/matches/{tx['match']['id']}", json={"accept": False},
                    headers=auth(user))
    assert r.status_code == 409


def test_rejected_match_is_never_suggested_again(client, app_db, worker_db, company, user):
    post_manual(app_db, company, user, simple_draft(50000, date(2026, 3, 10)))
    upload(client, company, user, camt([entry("625.00", "DBIT", "2026-03-12", ref="N1")]))
    run_reconcile(worker_db, company)
    [tx] = transactions(client, company, user)
    client.post(f"/companies/{company}/bank/matches/{tx['match']['id']}", json={"accept": False},
                headers=auth(user))
    run_reconcile(worker_db, company)
    [tx] = transactions(client, company, user)
    assert tx["status"] == "missing_document" and tx["match"] is None


def test_no_guess_when_two_vouchers_are_equally_close(client, app_db, worker_db, company, user):
    post_manual(app_db, company, user, simple_draft(50000, date(2026, 3, 10)))
    post_manual(app_db, company, user, simple_draft(50000, date(2026, 3, 14)))
    upload(client, company, user, camt([entry("625.00", "DBIT", "2026-03-12", ref="T1")]))
    run_reconcile(worker_db, company)
    assert transactions(client, company, user)[0]["status"] == "missing_document"


def test_closest_date_wins_and_says_so(client, app_db, worker_db, company, user):
    post_manual(app_db, company, user, simple_draft(50000, date(2026, 3, 2)))
    post_manual(app_db, company, user, simple_draft(50000, date(2026, 3, 11)))
    upload(client, company, user, camt([entry("625.00", "DBIT", "2026-03-12", ref="C1")]))
    run_reconcile(worker_db, company)
    [tx] = transactions(client, company, user)
    assert tx["match"]["method"] == "closest_date" and "Kontroller" in tx["match"]["explanation"]
    assert tx["voucher"]["voucher_date"] == "2026-03-11"


def test_outside_date_window_is_not_matched(client, app_db, worker_db, company, user):
    post_manual(app_db, company, user, simple_draft(50000, date(2026, 2, 1)))
    upload(client, company, user, camt([entry("625.00", "DBIT", "2026-03-12", ref="W1")]))
    run_reconcile(worker_db, company)
    assert transactions(client, company, user)[0]["status"] == "missing_document"


def test_receipt_posted_after_import_is_matched_by_queued_job(client, app_db, worker_db, storage, company, user):
    from test_review_two_clicks import base, pending_proposal

    upload(client, company, user, camt([entry("625.00", "DBIT", "2026-03-12", ref="L1")]))
    run_reconcile(worker_db, company)
    assert transactions(client, company, user)[0]["status"] == "missing_document"
    pid = pending_proposal(client, app_db, worker_db, storage, company, user)  # kvittering 10.3, 625 kr
    token = client.post(base(company, pid) + "/review", headers=auth(user)).json()["review_token"]
    r = client.post(base(company, pid) + "/approve", json={"confirm": True, "review_token": token},
                    headers=auth(user))
    assert r.status_code == 200, r.text
    run_reconcile(worker_db, company)  # godkjenningen la en avstemmingsjobb i kø
    assert transactions(client, company, user)[0]["status"] == "suggested"


# ---------------------------------------------------------------------------
# Forslag fra banklinjer (gebyr og renter)
# ---------------------------------------------------------------------------
def test_rules_classify_only_clear_cases():
    assert rules.classify(-5000, "PMNT/MDOP/CHRG", None) is rules.FEE
    assert rules.classify(-5000, None, "Gebyr nettbank") is rules.FEE
    assert rules.classify(1200, None, "Kreditrenter") is rules.INTEREST_IN
    assert rules.classify(-1200, "ACMT/MDOP/INTR", None) is rules.INTEREST_OUT
    assert rules.classify(-5000, None, "Rema 1000") is None
    assert rules.classify(5000, None, "Gebyr refundert") is None  # gebyr inn: ikke en regel
    assert rules.classify(-5000, None, "Renter og gebyr") is None  # tvetydig


def test_fee_becomes_proposal_and_two_click_approval_reconciles_it(client, app_db, worker_db, company, user):
    upload(client, company, user, camt([entry("45.00", "DBIT", "2026-03-31", ref="F1", text="Gebyr nettbank",
                                              code=("PMNT", "MDOP", "CHRG"))]))
    run_reconcile(worker_db, company)
    [tx] = transactions(client, company, user)
    assert tx["status"] == "proposed" and tx["proposal_id"]
    pid = tx["proposal_id"]
    p = client.get(f"/companies/{company}/proposals/{pid}", headers=auth(user)).json()
    assert p["document"] is None and p["bank_transaction"]["amount_ore"] == -4500
    assert p["model"] == "rules" and "7770" in p["explanation"] and "dokumentasjonen" in p["explanation"]
    assert [(ln["account"], ln["amount_ore"]) for ln in p["draft"]["lines"]] == [("7770", 4500), ("1920", -4500)]

    # Ett klikk er ikke nok.
    r = client.post(f"/companies/{company}/proposals/{pid}/approve",
                    json={"review_token": "x" * 20, "confirm": True}, headers=auth(user))
    assert r.status_code == 403
    token = client.post(f"/companies/{company}/proposals/{pid}/review", headers=auth(user)).json()["review_token"]
    r = client.post(f"/companies/{company}/proposals/{pid}/approve",
                    json={"review_token": token, "confirm": True}, headers=auth(user))
    assert r.status_code == 200, r.text
    assert r.json()["document_id"] is None
    [tx] = transactions(client, company, user)
    assert tx["status"] == "matched" and tx["match"]["method"] == "from_proposal"
    # Kjøres avstemmingen igjen, lages ingen nye forslag eller koblinger.
    run_reconcile(worker_db, company)
    with app_db.tx(user) as conn:
        assert conn.execute("select count(*) n from bokbuzz.proposals where company_id = %s",
                            [company]).fetchone()["n"] == 1


def test_interest_income_proposal_has_right_direction(client, worker_db, company, user):
    upload(client, company, user, camt([entry("12.34", "CRDT", "2026-03-31", ref="I9", text="Kreditrenter")]))
    run_reconcile(worker_db, company)
    pid = transactions(client, company, user)[0]["proposal_id"]
    p = client.get(f"/companies/{company}/proposals/{pid}", headers=auth(user)).json()
    assert [(ln["account"], ln["amount_ore"]) for ln in p["draft"]["lines"]] == [("8050", -1234), ("1920", 1234)]


def test_rejected_bank_proposal_is_not_recreated(client, worker_db, company, user):
    upload(client, company, user, camt([entry("45.00", "DBIT", "2026-03-31", ref="F2", text="Gebyr")]))
    run_reconcile(worker_db, company)
    pid = transactions(client, company, user)[0]["proposal_id"]
    r = client.post(f"/companies/{company}/proposals/{pid}/reject", json={"reason": "Feil"}, headers=auth(user))
    assert r.status_code == 200
    run_reconcile(worker_db, company)
    [tx] = transactions(client, company, user)
    assert tx["status"] == "missing_document" and tx["proposal_id"] is None


# ---------------------------------------------------------------------------
# Avstemmingsstatus
# ---------------------------------------------------------------------------
def test_reconciliation_compares_bank_and_ledger_balance(client, app_db, worker_db, company, user):
    post_manual(app_db, company, user, simple_draft(50000, date(2026, 3, 10)))  # -625 kr på 1920
    upload(client, company, user, camt([entry("625.00", "DBIT", "2026-03-12", ref="B1")],
                                       opening="0.00", closing="-625.00"))
    run_reconcile(worker_db, company)
    [acc] = client.get(f"/companies/{company}/bank/reconciliation", headers=auth(user)).json()
    assert acc["bank_balance_ore"] == -62500 and acc["ledger_balance_ore"] == -62500
    assert acc["difference_ore"] == 0 and acc["counts"] == {"suggested": 1}
