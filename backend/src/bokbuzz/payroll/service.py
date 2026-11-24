"""Lønn L0: innstillinger, ansatte, lønnskjøring, bokføring, betalingsfil og lønnsslipp.

Flyt:
1. Kunden oppretter en kjøring for en måned (utkast med én linje per aktiv ansatt).
2. Kunden justerer timer, bonus eller trekk. Alt beregnes på nytt.
3. Kunden ser oppsummeringen og bilaget (steg 1) og godkjenner med hashen av det hun så (steg 2).
   Lønnsbilaget bokføres via post_voucher. Kjøringen er låst etterpå.
4. Kunden laster ned betalingsfilen og godkjenner betalingene i nettbanken.

A-melding sendes ikke herfra ennå (L1). Til da sender kunden A-meldingen i Altinn."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from uuid import UUID

from .. import audit
from ..bank import service as bank
from ..db import Conn
from ..errors import Conflict, NotFound, ValidationFailed
from ..ledger import service as ledger
from ..ledger.models import DraftLine, VoucherDraft, content_hash
from ..ledger.service import POSTING_ROLES, require_role
from . import calc, pain001
from .validation import valid_bank_account, valid_national_id

PAYROLL_ROLES = POSTING_ROLES
MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober",
          "november", "desember"]


# ---------------------------------------------------------------------------
# Innstillinger
# ---------------------------------------------------------------------------
def get_settings(conn: Conn, company_id: UUID) -> dict | None:
    return conn.execute("select * from bokbuzz.payroll_settings where company_id = %s", [company_id]).fetchone()


def save_settings(conn: Conn, *, company_id: UUID, actor: UUID, data: dict) -> dict:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    for key in ("pay_from_account", "tax_withholding_account", "tax_authority_account"):
        if data.get(key) and not valid_bank_account(data[key]):
            raise ValidationFailed(f"Ugyldig kontonummer i {key}", code="invalid_account")
    row = conn.execute(
        "insert into bokbuzz.payroll_settings (company_id, aga_zone, holiday_rate_bp, pay_from_account,"
        " tax_withholding_account, kid_withholding, kid_aga, tax_authority_account, updated_by)"
        " values (%(c)s, %(aga_zone)s, %(holiday_rate_bp)s, %(pay_from_account)s, %(tax_withholding_account)s,"
        " %(kid_withholding)s, %(kid_aga)s, %(tax_authority_account)s, %(u)s)"
        " on conflict (company_id) do update set aga_zone = excluded.aga_zone,"
        " holiday_rate_bp = excluded.holiday_rate_bp, pay_from_account = excluded.pay_from_account,"
        " tax_withholding_account = excluded.tax_withholding_account, kid_withholding = excluded.kid_withholding,"
        " kid_aga = excluded.kid_aga, tax_authority_account = excluded.tax_authority_account,"
        " updated_at = now(), updated_by = excluded.updated_by returning *",
        {**data, "c": company_id, "u": actor},
    ).fetchone()
    audit.record(conn, company_id=company_id, actor=actor, event_type="payroll.settings_saved",
                 entity_type="company", entity_id=company_id,
                 payload={k: data.get(k) for k in ("aga_zone", "holiday_rate_bp")})
    return row


def _require_settings(conn: Conn, company_id: UUID) -> dict:
    s = get_settings(conn, company_id)
    if not s:
        raise ValidationFailed("Lønnsinnstillingene må fylles ut først", code="payroll_settings_missing")
    return s


# ---------------------------------------------------------------------------
# Ansatte
# ---------------------------------------------------------------------------
EMPLOYEE_FIELDS = ("national_id", "name", "email", "bank_account", "position_pct_bp", "pay_type",
                   "monthly_salary_ore", "hourly_rate_ore", "tax_card_kind", "tax_percent", "tax_table",
                   "start_date", "end_date")


def _check_employee(data: dict) -> None:
    if not valid_national_id(data["national_id"]):
        raise ValidationFailed("Ugyldig fødselsnummer eller d-nummer", code="invalid_national_id")
    if not valid_bank_account(data["bank_account"]):
        raise ValidationFailed("Ugyldig kontonummer", code="invalid_account")


def create_employee(conn: Conn, *, company_id: UUID, actor: UUID, data: dict) -> dict:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    _check_employee(data)
    cols = ", ".join(EMPLOYEE_FIELDS)
    vals = ", ".join(f"%({k})s" for k in EMPLOYEE_FIELDS)
    row = conn.execute(f"insert into bokbuzz.employees (company_id, {cols}) values (%(c)s, {vals}) returning *",
                       {**data, "c": company_id}).fetchone()
    audit.record(conn, company_id=company_id, actor=actor, event_type="employee.created",
                 entity_type="employee", entity_id=row["id"], payload={"name": row["name"]})
    return row


def update_employee(conn: Conn, *, company_id: UUID, actor: UUID, employee_id: UUID, data: dict) -> dict:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    _check_employee(data)
    sets = ", ".join(f"{k} = %({k})s" for k in EMPLOYEE_FIELDS)
    row = conn.execute(
        f"update bokbuzz.employees set {sets} where company_id = %(c)s and id = %(e)s returning *",
        {**data, "c": company_id, "e": employee_id},
    ).fetchone()
    if not row:
        raise NotFound("Den ansatte finnes ikke")
    audit.record(conn, company_id=company_id, actor=actor, event_type="employee.updated",
                 entity_type="employee", entity_id=employee_id, payload={"name": row["name"]})
    return row


def list_employees(conn: Conn, company_id: UUID, actor: UUID) -> list[dict]:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    return conn.execute("select * from bokbuzz.employees where company_id = %s order by name",
                        [company_id]).fetchall()


# ---------------------------------------------------------------------------
# Lønnskjøring
# ---------------------------------------------------------------------------
def _terms(emp: dict) -> calc.EmployeeTerms:
    return calc.EmployeeTerms(pay_type=emp["pay_type"], monthly_salary_ore=emp["monthly_salary_ore"],
                              hourly_rate_ore=emp["hourly_rate_ore"], tax_card_kind=emp["tax_card_kind"],
                              tax_percent=emp["tax_percent"])


def _aga_rate(conn: Conn, zone: str, on: date) -> int:
    row = conn.execute(
        "select rate_bp from bokbuzz.aga_rates where zone = %s and valid_from <= %s"
        " and (valid_to is null or valid_to >= %s)", [zone, on, on]).fetchone()
    if not row:
        raise ValidationFailed(f"Mangler sats for arbeidsgiveravgift i sone {zone}", code="aga_rate_missing")
    return row["rate_bp"]


def _write_line(conn: Conn, run: dict, emp: dict, inp: calc.LineInput, note: str | None) -> calc.LineResult:
    res = calc.calculate(_terms(emp), inp, aga_rate_bp=run["aga_rate_bp"], holiday_rate_bp=run["holiday_rate_bp"])
    conn.execute(
        "insert into bokbuzz.payroll_lines (run_id, company_id, employee_id, hours_x100, base_ore, bonus_ore,"
        " gross_ore, tax_ore, tax_manual, holiday_pay_ore, aga_ore, aga_holiday_ore, net_ore, note)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " on conflict (run_id, employee_id) do update set hours_x100 = excluded.hours_x100,"
        " base_ore = excluded.base_ore, bonus_ore = excluded.bonus_ore, gross_ore = excluded.gross_ore,"
        " tax_ore = excluded.tax_ore, tax_manual = excluded.tax_manual, holiday_pay_ore = excluded.holiday_pay_ore,"
        " aga_ore = excluded.aga_ore, aga_holiday_ore = excluded.aga_holiday_ore, net_ore = excluded.net_ore,"
        " note = excluded.note",
        [run["id"], run["company_id"], emp["id"], res.hours_x100, res.base_ore, res.bonus_ore, res.gross_ore,
         res.tax_ore, res.tax_manual, res.holiday_pay_ore, res.aga_ore, res.aga_holiday_ore, res.net_ore, note],
    )
    return res


def create_run(conn: Conn, *, company_id: UUID, actor: UUID, year: int, month: int, pay_date: date) -> dict:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    settings = _require_settings(conn, company_id)
    if not 1 <= month <= 12:
        raise ValidationFailed("Ugyldig måned", code="invalid_month")
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    employees = conn.execute(
        "select * from bokbuzz.employees where company_id = %s and start_date <= %s"
        " and (end_date is null or end_date >= %s) order by name", [company_id, last, first]).fetchall()
    if not employees:
        raise ValidationFailed("Ingen ansatte er aktive i måneden", code="no_employees")
    try:
        run = conn.execute(
            "insert into bokbuzz.payroll_runs (company_id, year, month, pay_date, aga_zone, aga_rate_bp,"
            " holiday_rate_bp, created_by) values (%s, %s, %s, %s, %s, %s, %s, %s) returning *",
            [company_id, year, month, pay_date, settings["aga_zone"], _aga_rate(conn, settings["aga_zone"], pay_date),
             settings["holiday_rate_bp"], actor],
        ).fetchone()
    except Exception as exc:
        if "payroll_runs_one_per_month" in str(exc):
            raise Conflict("Det finnes allerede en lønnskjøring for måneden", code="run_exists") from exc
        raise
    for emp in employees:
        _write_line(conn, run, emp, calc.LineInput(), None)
    audit.record(conn, company_id=company_id, actor=actor, event_type="payroll.run_created",
                 entity_type="payroll_run", entity_id=run["id"], payload={"year": year, "month": month})
    return run


def _run(conn: Conn, company_id: UUID, run_id: UUID, *, lock: bool = False) -> dict:
    row = conn.execute(
        "select * from bokbuzz.payroll_runs where company_id = %s and id = %s" + (" for update" if lock else ""),
        [company_id, run_id]).fetchone()
    if not row:
        raise NotFound("Lønnskjøringen finnes ikke")
    return row


def update_line(conn: Conn, *, company_id: UUID, actor: UUID, run_id: UUID, employee_id: UUID,
                inp: calc.LineInput, note: str | None) -> dict:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    run = _run(conn, company_id, run_id, lock=True)
    if run["status"] != "draft":
        raise Conflict("Lønnskjøringen er godkjent og kan ikke endres", code="run_locked")
    emp = conn.execute("select e.* from bokbuzz.employees e join bokbuzz.payroll_lines l on l.employee_id = e.id"
                       " where l.run_id = %s and e.id = %s", [run_id, employee_id]).fetchone()
    if not emp:
        raise NotFound("Den ansatte er ikke med i kjøringen")
    _write_line(conn, run, emp, inp, note)
    return summary(conn, company_id, run_id)


def _lines(conn: Conn, run_id: UUID) -> list[dict]:
    return conn.execute(
        "select l.*, e.name, e.bank_account, e.tax_card_kind, e.tax_percent, e.tax_table, e.pay_type,"
        " e.hourly_rate_ore, e.monthly_salary_ore"
        " from bokbuzz.payroll_lines l join bokbuzz.employees e on e.id = l.employee_id"
        " where l.run_id = %s order by e.name", [run_id]).fetchall()


def voucher_draft(run: dict, lines: list[dict], settings: dict) -> VoucherDraft:
    """Lønnsbilaget. Nettolønn føres mot bankkontoen per ansatt, slik at hver utbetaling kan
    avstemmes mot kontoutskriften."""
    label = f"{MONTHS[run['month'] - 1]} {run['year']}"
    out: list[DraftLine] = []

    def add(account: str, amount: int, text: str) -> None:
        if amount:
            out.append(DraftLine(account=account, amount_ore=amount, description=text[:300]))

    for ln in lines:
        add("5000", ln["gross_ore"], f"Lønn {label}: {ln['name']}")
    add("2600", -sum(ln["tax_ore"] for ln in lines), f"Forskuddstrekk {label}")
    for ln in lines:
        add("1920", -ln["net_ore"], f"Utbetalt lønn: {ln['name']}")
    tax = sum(ln["tax_ore"] for ln in lines)
    if settings.get("tax_withholding_account"):
        add("1950", tax, "Overført til skattetrekkskonto")
        add("1920", -tax, "Overført til skattetrekkskonto")
    add("5400", sum(ln["aga_ore"] for ln in lines), f"Arbeidsgiveravgift {label}")
    add("2770", -sum(ln["aga_ore"] for ln in lines), f"Arbeidsgiveravgift {label}")
    add("5180", sum(ln["holiday_pay_ore"] for ln in lines), f"Feriepenger {label}")
    add("2940", -sum(ln["holiday_pay_ore"] for ln in lines), f"Feriepenger {label}")
    add("5420", sum(ln["aga_holiday_ore"] for ln in lines), f"Arbeidsgiveravgift av feriepenger {label}")
    add("2785", -sum(ln["aga_holiday_ore"] for ln in lines), f"Arbeidsgiveravgift av feriepenger {label}")
    return VoucherDraft(voucher_date=run["pay_date"], description=f"Lønn {label}", lines=out)


def summary(conn: Conn, company_id: UUID, run_id: UUID) -> dict:
    run = _run(conn, company_id, run_id)
    settings = _require_settings(conn, company_id)
    lines = _lines(conn, run_id)
    warnings: list[dict] = []
    for ln in lines:
        if ln["pay_type"] == "hourly" and not ln["hours_x100"] and ln["base_ore"] == 0:
            warnings.append({"code": "hours_missing", "employee": ln["name"], "blocking": True,
                             "message": f"{ln['name']}: timer mangler"})
        if ln["tax_card_kind"] == "table" and not ln["tax_manual"] and ln["gross_ore"] > 0:
            warnings.append({"code": "table_tax_missing", "employee": ln["name"], "blocking": True,
                             "message": f"{ln['name']} har tabellkort ({ln['tax_table']}). Legg inn trekket fra "
                                        "Skatteetatens trekktabell."})
    if not settings.get("tax_withholding_account"):
        warnings.append({"code": "no_withholding_account", "blocking": False,
                         "message": "Skattetrekkskonto mangler. Trekket skal stå på egen konto (eller bankgaranti)."})
    if run["aga_zone"] == "1a":
        warnings.append({"code": "zone_1a", "blocking": False,
                         "message": "Sone 1a: Bokbuzz følger ikke opp fribeløpet ennå. Kontroller avgiften."})
    totals = {k: sum(ln[k] for ln in lines) for k in
              ("gross_ore", "tax_ore", "net_ore", "aga_ore", "holiday_pay_ore", "aga_holiday_ore")}
    draft = voucher_draft(run, lines, settings) if lines else None
    return {"run": run, "lines": lines, "totals": totals, "warnings": warnings,
            "voucher_draft": draft.model_dump(mode="json") if draft else None,
            "content_hash": content_hash(draft) if draft else None,
            "a_melding_due": _a_melding_due(run["year"], run["month"])}


def _a_melding_due(year: int, month: int) -> date:
    """A-meldingen leveres innen den 5. i måneden etter (verifiser forskyvning ved helg)."""
    return date(year + (month == 12), month % 12 + 1, 5)


def approve_run(conn: Conn, *, company_id: UUID, actor: UUID, run_id: UUID, content_hash_seen: str,
                confirm: bool) -> dict:
    """Steg 2: kunden godkjenner nøyaktig det bilaget hun så i oppsummeringen."""
    if confirm is not True:
        raise ValidationFailed("Godkjenning må bekreftes eksplisitt", code="confirm_required")
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    run = _run(conn, company_id, run_id, lock=True)
    if run["status"] != "draft":
        raise Conflict("Lønnskjøringen er allerede behandlet", code="run_decided")
    s = summary(conn, company_id, run_id)
    if any(w["blocking"] for w in s["warnings"]):
        raise ValidationFailed("Rett opp merknadene før godkjenning", code="run_has_problems")
    if s["content_hash"] != content_hash_seen:
        raise Conflict("Lønnskjøringen er endret siden du så den. Se over på nytt.", code="run_changed")
    draft = VoucherDraft.model_validate(s["voucher_draft"])
    approval = ledger.create_approval(conn, company_id=company_id, actor=actor, kind="manual", request=draft)
    voucher = ledger.post_voucher(conn, company_id=company_id, actor=actor, request=draft, approval_id=approval,
                                  idempotency_key=f"payroll:{run_id}")
    row = conn.execute(
        "update bokbuzz.payroll_runs set status = 'approved', content_hash = %s, voucher_id = %s,"
        " approved_by = %s, approved_at = now() where id = %s returning *",
        [s["content_hash"], voucher.id, actor, run_id]).fetchone()
    audit.record(conn, company_id=company_id, actor=actor, event_type="payroll.run_approved",
                 entity_type="payroll_run", entity_id=run_id,
                 payload={"voucher_id": str(voucher.id), "content_hash": s["content_hash"], **s["totals"]})
    bank.request_reconcile(conn, company_id, "payroll", str(run_id))
    return {"run": row, "voucher": voucher.model_dump(mode="json")}


def cancel_run(conn: Conn, *, company_id: UUID, actor: UUID, run_id: UUID) -> dict:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    run = _run(conn, company_id, run_id, lock=True)
    if run["status"] != "draft":
        raise Conflict("Bare utkast kan forkastes. Godkjent lønn rettes med ny kjøring eller reversering.",
                       code="run_locked")
    row = conn.execute("update bokbuzz.payroll_runs set status = 'cancelled' where id = %s returning *",
                       [run_id]).fetchone()
    audit.record(conn, company_id=company_id, actor=actor, event_type="payroll.run_cancelled",
                 entity_type="payroll_run", entity_id=run_id)
    return row


def list_runs(conn: Conn, company_id: UUID, actor: UUID) -> list[dict]:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    return conn.execute(
        "select r.*, coalesce(sum(l.gross_ore), 0)::bigint as gross_ore, coalesce(sum(l.net_ore), 0)::bigint"
        " as net_ore, count(l.*)::int as employees from bokbuzz.payroll_runs r"
        " left join bokbuzz.payroll_lines l on l.run_id = r.id where r.company_id = %s and r.status <> 'cancelled'"
        " group by r.id order by r.year desc, r.month desc", [company_id]).fetchall()


# ---------------------------------------------------------------------------
# Betalinger og lønnsslipp
# ---------------------------------------------------------------------------
def payment_file(conn: Conn, *, company_id: UUID, actor: UUID, run_id: UUID) -> str:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    run = _run(conn, company_id, run_id)
    if run["status"] != "approved":
        raise Conflict("Lønnskjøringen må godkjennes før betalingsfilen lages", code="run_not_approved")
    settings = _require_settings(conn, company_id)
    company = conn.execute("select name from bokbuzz.companies where id = %s", [company_id]).fetchone()
    label = f"{MONTHS[run['month'] - 1]} {run['year']}"
    payments = [pain001.Payment(end_to_end_id=f"L{run['year']}{run['month']:02d}-{i + 1}", amount_ore=ln["net_ore"],
                                creditor_name=ln["name"], creditor_account=ln["bank_account"],
                                message=f"Lønn {label}", salary=True)
                for i, ln in enumerate(_lines(conn, run_id)) if ln["net_ore"] > 0]
    tax = sum(ln["tax_ore"] for ln in _lines(conn, run_id))
    if tax and settings.get("tax_withholding_account"):
        payments.append(pain001.Payment(end_to_end_id=f"T{run['year']}{run['month']:02d}", amount_ore=tax,
                                        creditor_name=company["name"],
                                        creditor_account=settings["tax_withholding_account"],
                                        message=f"Skattetrekk {label}"))
    audit.record(conn, company_id=company_id, actor=actor, event_type="payroll.payment_file_created",
                 entity_type="payroll_run", entity_id=run_id, payload={"payments": len(payments)})
    return pain001.build(message_id=f"BB-{str(run_id)[:8]}-{datetime.now(UTC):%Y%m%d%H%M%S}",
                         debtor_name=company["name"], debtor_account=settings["pay_from_account"],
                         execution_date=run["pay_date"], payments=payments, created=datetime.now(UTC))


def term_payments(conn: Conn, *, company_id: UUID, actor: UUID, year: int, term: int) -> dict:
    """Skattetrekk og arbeidsgiveravgift for en termin (to måneder), med KID og forfall.
    Forfall: den 15. i måneden etter terminen (verifiser mot skatteetaten.no)."""
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    if not 1 <= term <= 6:
        raise ValidationFailed("Termin må være 1–6", code="invalid_term")
    settings = _require_settings(conn, company_id)
    row = conn.execute(
        "select coalesce(sum(l.tax_ore), 0)::bigint as tax, coalesce(sum(l.aga_ore), 0)::bigint as aga"
        " from bokbuzz.payroll_lines l join bokbuzz.payroll_runs r on r.id = l.run_id"
        " where r.company_id = %s and r.status = 'approved' and r.year = %s and r.month in (%s, %s)",
        [company_id, year, 2 * term - 1, 2 * term]).fetchone()
    due = date(year + (term == 6), (2 * term) % 12 + 1, 15)
    missing = [k for k in ("kid_withholding", "kid_aga", "tax_authority_account") if not settings.get(k)]
    return {"year": year, "term": term, "due": due, "withholding_ore": row["tax"], "aga_ore": row["aga"],
            "kid_withholding": settings.get("kid_withholding"), "kid_aga": settings.get("kid_aga"),
            "tax_authority_account": settings.get("tax_authority_account"), "missing": missing}


def term_payment_file(conn: Conn, *, company_id: UUID, actor: UUID, year: int, term: int, kind: str) -> str:
    info = term_payments(conn, company_id=company_id, actor=actor, year=year, term=term)
    if info["missing"]:
        raise ValidationFailed("KID og Skatteetatens kontonummer må legges inn i lønnsinnstillingene",
                               code="payroll_settings_missing")
    settings = _require_settings(conn, company_id)
    company = conn.execute("select name from bokbuzz.companies where id = %s", [company_id]).fetchone()
    if kind == "withholding":
        amount, kid = info["withholding_ore"], info["kid_withholding"]
        debtor = settings.get("tax_withholding_account") or settings["pay_from_account"]
    elif kind == "aga":
        amount, kid, debtor = info["aga_ore"], info["kid_aga"], settings["pay_from_account"]
    else:
        raise ValidationFailed("Ukjent betalingstype", code="invalid_kind")
    if amount <= 0:
        raise ValidationFailed("Ingenting å betale for terminen", code="nothing_to_pay")
    audit.record(conn, company_id=company_id, actor=actor, event_type="payroll.term_payment_file_created",
                 entity_type="company", entity_id=company_id, payload={"year": year, "term": term, "kind": kind})
    return pain001.build(
        message_id=f"BB-{kind[:3].upper()}-{year}{term}-{datetime.now(UTC):%Y%m%d%H%M%S}", debtor_name=company["name"],
        debtor_account=debtor, execution_date=info["due"], created=datetime.now(UTC),
        payments=[pain001.Payment(end_to_end_id=f"{kind[:3].upper()}{year}T{term}", amount_ore=amount,
                                  creditor_name="Skatteetaten", creditor_account=info["tax_authority_account"],
                                  kid=kid)])


def payslip(conn: Conn, *, company_id: UUID, actor: UUID, run_id: UUID, employee_id: UUID) -> dict:
    require_role(conn, company_id, actor, PAYROLL_ROLES)
    run = _run(conn, company_id, run_id)
    line = next((ln for ln in _lines(conn, run_id) if ln["employee_id"] == employee_id), None)
    if not line:
        raise NotFound("Lønnsslippen finnes ikke")
    company = conn.execute("select name, orgnr from bokbuzz.companies where id = %s", [company_id]).fetchone()
    ytd = conn.execute(
        "select coalesce(sum(l.gross_ore), 0)::bigint as gross, coalesce(sum(l.tax_ore), 0)::bigint as tax,"
        " coalesce(sum(l.holiday_pay_ore), 0)::bigint as holiday"
        " from bokbuzz.payroll_lines l join bokbuzz.payroll_runs r on r.id = l.run_id"
        " where r.company_id = %s and l.employee_id = %s and r.year = %s and r.month <= %s"
        " and (r.status = 'approved' or r.id = %s)",
        [company_id, employee_id, run["year"], run["month"], run_id]).fetchone()
    return {"company": company, "run": run, "line": line,
            "period": f"{MONTHS[run['month'] - 1]} {run['year']}", "year_to_date": ytd}
