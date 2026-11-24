"""Lønn L0: beregning, lønnskjøring i to steg, låsing, betalingsfil og terminbetalinger."""

from __future__ import annotations

import random
import uuid
from datetime import date

import psycopg
import pytest
from conftest import add_member, auth
from defusedxml import ElementTree as ET

from bokbuzz.payroll import calc
from bokbuzz.payroll.pain001 import NS
from bokbuzz.payroll.validation import valid_bank_account, valid_national_id

_ACC_W = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
_K1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
_K2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]


def _check(digits: list[int], weights: list[int]) -> int | None:
    rest = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11
    c = 0 if rest == 0 else 11 - rest
    return None if c == 10 else c


def account() -> str:
    while True:
        d = [random.randint(1, 9)] + [random.randint(0, 9) for _ in range(9)]
        c = _check(d, _ACC_W)
        if c is not None:
            return "".join(map(str, d + [c]))


def fnr() -> str:
    while True:
        d = [int(x) for x in f"{random.randint(1, 28):02d}{random.randint(1, 12):02d}{random.randint(60, 99)}"]
        d += [random.randint(0, 9) for _ in range(3)]
        k1 = _check(d, _K1)
        if k1 is None:
            continue
        k2 = _check(d + [k1], _K2)
        if k2 is not None:
            return "".join(map(str, d + [k1, k2]))


def base(company) -> str:
    return f"/companies/{company}"


def setup_payroll(client, company, user, **over) -> dict:
    body = {"aga_zone": "1", "holiday_rate_bp": 1020, "pay_from_account": account(),
            "tax_withholding_account": account(), "kid_withholding": "12345678901", "kid_aga": "98765432109",
            "tax_authority_account": account(), **over}
    r = client.put(base(company) + "/payroll/settings", json=body, headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


def employee(client, company, user, **over) -> dict:
    body = {"national_id": fnr(), "name": "Kari Nordmann", "bank_account": account(), "pay_type": "monthly",
            "monthly_salary_ore": 5_000_000, "tax_card_kind": "percent", "tax_percent": 30,
            "start_date": "2026-01-01", **over}
    r = client.post(base(company) + "/employees", json=body, headers=auth(user))
    assert r.status_code == 201, r.text
    return r.json()


def new_run(client, company, user, month=3, pay_date="2026-03-20") -> dict:
    r = client.post(base(company) + "/payroll/runs", json={"year": 2026, "month": month, "pay_date": pay_date},
                    headers=auth(user))
    assert r.status_code == 201, r.text
    return r.json()


def approve(client, company, user, s: dict):
    return client.post(base(company) + f"/payroll/runs/{s['run']['id']}/approve",
                       json={"content_hash": s["content_hash"], "confirm": True}, headers=auth(user))


# ---------------------------------------------------------------------------
# Regler
# ---------------------------------------------------------------------------
def test_identifier_checks():
    for _ in range(50):
        assert valid_bank_account(account()) and valid_national_id(fnr())
    a = account()
    assert not valid_bank_account(a[:-1] + str((int(a[-1]) + 1) % 10))
    assert not valid_national_id("12345678901")


def test_monthly_salary_percent_card():
    r = calc.calculate(calc.EmployeeTerms("monthly", 5_000_000, None, "percent", 30), calc.LineInput(),
                       aga_rate_bp=1410, holiday_rate_bp=1020)
    assert (r.gross_ore, r.tax_ore, r.net_ore) == (5_000_000, 1_500_000, 3_500_000)
    assert (r.holiday_pay_ore, r.aga_ore, r.aga_holiday_ore) == (510_000, 705_000, 71_910)


def test_percent_tax_rounds_down_to_whole_kroner():
    assert calc.percent_tax(3_333_333, 30) == 999_900


def test_hourly_and_bonus_and_manual_tax():
    r = calc.calculate(calc.EmployeeTerms("hourly", None, 25_000, "table", None),
                       calc.LineInput(hours_x100=3750, bonus_ore=100_000, tax_override_ore=200_000),
                       aga_rate_bp=1410, holiday_rate_bp=1200)
    assert (r.base_ore, r.gross_ore, r.tax_ore, r.tax_manual) == (937_500, 1_037_500, 200_000, True)
    assert r.holiday_pay_ore == 124_500 and not r.problems


def test_table_card_without_manual_tax_is_a_problem():
    r = calc.calculate(calc.EmployeeTerms("monthly", 4_000_000, None, "table", None), calc.LineInput(),
                       aga_rate_bp=1410, holiday_rate_bp=1020)
    assert r.tax_ore == 0 and r.problems


# ---------------------------------------------------------------------------
# Lønnskjøring
# ---------------------------------------------------------------------------
def test_full_run_posts_balanced_voucher_and_locks(client, app_db, admin, company, user):
    setup_payroll(client, company, user)
    kari = employee(client, company, user)
    ola = employee(client, company, user, name="Ola Timelønn", pay_type="hourly", monthly_salary_ore=None,
                   hourly_rate_ore=25_000, tax_percent=20)
    s = new_run(client, company, user)
    assert {w["code"] for w in s["warnings"]} == {"hours_missing"}
    r = approve(client, company, user, s)
    assert r.status_code == 422  # timer mangler

    r = client.post(base(company) + f"/payroll/runs/{s['run']['id']}/lines/{ola['id']}",
                    json={"hours_x100": 4000}, headers=auth(user))
    assert r.status_code == 200, r.text
    stale = s
    s = r.json()
    assert s["totals"]["gross_ore"] == 5_000_000 + 1_000_000 and s["warnings"] == []
    assert approve(client, company, user, stale).status_code == 409  # godkjenner bare det kunden så

    r = approve(client, company, user, s)
    assert r.status_code == 200, r.text
    v = r.json()["voucher"]
    assert sum(ln["amount_ore"] for ln in v["lines"]) == 0
    by = {}
    for ln in v["lines"]:
        by[ln["account"]] = by.get(ln["account"], 0) + ln["amount_ore"]
    assert by["5000"] == 6_000_000 and by["2600"] == -(1_500_000 + 200_000)
    assert by["1950"] == 1_700_000 and by["2770"] == -846_000 and by["2940"] == -612_000
    # Nettolønn føres per ansatt på bankkontoen, så hver utbetaling kan avstemmes.
    nets = sorted(ln["amount_ore"] for ln in v["lines"] if ln["account"] == "1920")
    assert nets == sorted([-3_500_000, -800_000, -1_700_000])

    # Låst etterpå, både i API-et og i databasen.
    r = client.post(base(company) + f"/payroll/runs/{s['run']['id']}/lines/{kari['id']}",
                    json={"bonus_ore": 1}, headers=auth(user))
    assert r.status_code == 409
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("update bokbuzz.payroll_lines set bonus_ore = 1 where run_id = %s", [s["run"]["id"]])
    assert client.post(base(company) + f"/payroll/runs/{s['run']['id']}/cancel", headers=auth(user)).status_code == 409


def test_table_card_needs_manual_tax_before_approval(client, company, user):
    setup_payroll(client, company, user)
    e = employee(client, company, user, tax_card_kind="table", tax_percent=None, tax_table="7100")
    s = new_run(client, company, user)
    assert [w["code"] for w in s["warnings"]] == ["table_tax_missing"]
    s = client.post(base(company) + f"/payroll/runs/{s['run']['id']}/lines/{e['id']}",
                    json={"tax_override_ore": 1_234_500}, headers=auth(user)).json()
    assert s["warnings"] == [] and s["lines"][0]["tax_manual"] is True
    assert approve(client, company, user, s).status_code == 200


def test_one_active_run_per_month_and_cancel(client, company, user):
    setup_payroll(client, company, user)
    employee(client, company, user)
    s = new_run(client, company, user)
    r = client.post(base(company) + "/payroll/runs", json={"year": 2026, "month": 3, "pay_date": "2026-03-20"},
                    headers=auth(user))
    assert r.status_code == 409
    assert client.post(base(company) + f"/payroll/runs/{s['run']['id']}/cancel",
                       headers=auth(user)).status_code == 200
    new_run(client, company, user)


def test_settings_required_and_employee_validation(client, company, user):
    r = client.post(base(company) + "/payroll/runs", json={"year": 2026, "month": 3, "pay_date": "2026-03-20"},
                    headers=auth(user))
    assert r.status_code == 422 and r.json()["error"] == "payroll_settings_missing"
    setup_payroll(client, company, user)
    body = {"national_id": "12345678901", "name": "X", "bank_account": account(), "pay_type": "monthly",
            "monthly_salary_ore": 100, "tax_percent": 10, "start_date": "2026-01-01"}
    r = client.post(base(company) + "/employees", json=body, headers=auth(user))
    assert r.status_code == 422 and r.json()["error"] == "invalid_national_id"


def test_reader_cannot_see_employees(client, admin, company, user):
    setup_payroll(client, company, user)
    employee(client, company, user)
    reader = uuid.uuid4()
    add_member(admin, company, reader, "reader")
    assert client.get(base(company) + "/employees", headers=auth(reader)).status_code == 403
    assert client.get(base(company) + "/payroll/settings", headers=auth(reader)).status_code == 403


# ---------------------------------------------------------------------------
# Betalinger
# ---------------------------------------------------------------------------
def test_payment_file_has_net_salaries_and_withholding_transfer(client, company, user):
    settings = setup_payroll(client, company, user)
    kari = employee(client, company, user)
    s = new_run(client, company, user)
    path = base(company) + f"/payroll/runs/{s['run']['id']}/payment-file"
    assert client.get(path, headers=auth(user)).status_code == 409  # ikke godkjent ennå
    approve(client, company, user, s)
    r = client.get(path, headers=auth(user))
    assert r.status_code == 200
    root = ET.fromstring(r.content)
    ns = {"p": NS}
    assert root.findtext(".//p:GrpHdr/p:NbOfTxs", namespaces=ns) == "2"
    assert root.findtext(".//p:GrpHdr/p:CtrlSum", namespaces=ns) == "50000.00"
    assert root.findtext(".//p:ReqdExctnDt", namespaces=ns) == "2026-03-20"
    assert root.findtext(".//p:DbtrAcct/p:Id/p:Othr/p:Id", namespaces=ns) == settings["pay_from_account"]
    txs = root.findall(".//p:CdtTrfTxInf", ns)
    salary = [t for t in txs if t.findtext("p:Purp/p:Cd", namespaces=ns) == "SALA"]
    assert len(salary) == 1 and salary[0].findtext(".//p:InstdAmt", namespaces=ns) == "35000.00"
    assert salary[0].findtext(".//p:CdtrAcct/p:Id/p:Othr/p:Id", namespaces=ns) == kari["bank_account"]
    [transfer] = [t for t in txs if t not in salary]
    assert transfer.findtext(".//p:CdtrAcct/p:Id/p:Othr/p:Id", namespaces=ns) == settings["tax_withholding_account"]


def test_term_payments_with_kid(client, company, user):
    settings = setup_payroll(client, company, user)
    employee(client, company, user)
    approve(client, company, user, new_run(client, company, user, month=3, pay_date="2026-03-20"))
    approve(client, company, user, new_run(client, company, user, month=4, pay_date="2026-04-20"))
    t = client.get(base(company) + "/payroll/terms/2026/2", headers=auth(user)).json()
    assert t["withholding_ore"] == 3_000_000 and t["aga_ore"] == 1_410_000 and t["due"] == "2026-05-15"
    assert t["missing"] == []
    r = client.get(base(company) + "/payroll/terms/2026/2/payment-file?kind=aga", headers=auth(user))
    root = ET.fromstring(r.content)
    ns = {"p": NS}
    assert root.findtext(".//p:CdtrRefInf/p:Ref", namespaces=ns) == "98765432109"
    assert root.findtext(".//p:CdtrRefInf/p:Tp/p:CdOrPrtry/p:Cd", namespaces=ns) == "SCOR"
    assert root.findtext(".//p:InstdAmt", namespaces=ns) == "14100.00"
    r = client.get(base(company) + "/payroll/terms/2026/2/payment-file?kind=withholding", headers=auth(user))
    root = ET.fromstring(r.content)
    assert root.findtext(".//p:DbtrAcct/p:Id/p:Othr/p:Id", namespaces=ns) == settings["tax_withholding_account"]
    assert root.findtext(".//p:CdtrRefInf/p:Ref", namespaces=ns) == "12345678901"
    # Termin 6 forfaller 15. januar året etter.
    assert client.get(base(company) + "/payroll/terms/2026/6", headers=auth(user)).json()["due"] == "2027-01-15"


def test_payslip_has_year_to_date(client, company, user):
    setup_payroll(client, company, user)
    e = employee(client, company, user)
    approve(client, company, user, new_run(client, company, user, month=1, pay_date="2026-01-20"))
    s = new_run(client, company, user, month=2, pay_date="2026-02-20")
    p = client.get(base(company) + f"/payroll/runs/{s['run']['id']}/payslips/{e['id']}", headers=auth(user)).json()
    assert p["period"] == "februar 2026" and p["line"]["net_ore"] == 3_500_000
    assert p["year_to_date"]["gross"] == 10_000_000


def test_salary_payment_is_reconciled_with_bank(client, worker_db, company, user):
    from test_bank import camt, entry, run_reconcile, transactions

    setup_payroll(client, company, user)
    employee(client, company, user)
    approve(client, company, user, new_run(client, company, user))
    client.post(base(company) + "/bank/statements", headers=auth(user),
                files={"file": ("s.xml", camt([entry("35000.00", "DBIT", "2026-03-20", ref="SAL1",
                                                     name="Kari Nordmann")]), "application/xml")})
    run_reconcile(worker_db, company)
    [tx] = transactions(client, company, user)
    assert tx["status"] == "suggested" and tx["voucher"]["description"] == "Lønn mars 2026"


def test_aga_zone_rate_is_used(client, company, user):
    setup_payroll(client, company, user, aga_zone="4")
    employee(client, company, user)
    s = new_run(client, company, user)
    assert s["run"]["aga_rate_bp"] == 510 and s["totals"]["aga_ore"] == 255_000
    assert date.fromisoformat(s["a_melding_due"]) == date(2026, 4, 5)
