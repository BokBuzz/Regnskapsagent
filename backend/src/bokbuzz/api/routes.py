"""HTTP-ruter. Alle selskapsruter ligger under /companies/{company_id} og går
gjennom get_company, som krever medlemskap."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from .. import audit, brreg
from ..bank import service as bank
from ..documents import service as documents
from ..errors import NotFound, ValidationFailed
from ..ledger import service as ledger
from ..ledger.models import VoucherDraft
from ..ledger.money import oslo_today
from ..payroll import calc as payroll_calc
from ..payroll import service as payroll
from ..proposals.validation import valid_orgnr
from ..review import service as review
from ..vat import return_draft as vat_return
from ..vat.submission import NotConfigured
from .deps import CompanyDep, PrincipalDep, ServicesDep

router = APIRouter()


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------
@router.get("/health")
def health(services: ServicesDep) -> dict:
    with services.db.tx() as conn:
        conn.execute("select 1")
    return {"status": "ok"}


@router.get("/me")
def me(principal: PrincipalDep) -> dict:
    return {"user_id": principal.user_id, "mfa": principal.has_mfa, "email": principal.email}


@router.get("/vat-codes")
def vat_codes(principal: PrincipalDep, services: ServicesDep,
              on: Annotated[date | None, Query()] = None) -> list[dict]:
    """MVA-koder med sats på en dato (standard i dag), til nedtrekkslister i appen."""
    day = on or oslo_today()
    with services.db.tx(principal.user_id) as conn:
        return conn.execute(
            "select c.code, c.description, c.direction, r.rate_bp from bokbuzz.vat_codes c"
            " join bokbuzz.vat_rates r on r.code = c.code"
            " where r.valid_from <= %s and (r.valid_to is null or r.valid_to >= %s)"
            " order by c.direction, c.code::int", [day, day]).fetchall()


@router.get("/lookup/orgnr/{orgnr}")
def lookup_orgnr(orgnr: str, principal: PrincipalDep, services: ServicesDep) -> dict:
    """Henter navn, organisasjonsform og MVA-registrering fra Enhetsregisteret ved oppstart."""
    orgnr = orgnr.replace(" ", "")
    if not valid_orgnr(orgnr):
        raise ValidationFailed("Ugyldig organisasjonsnummer", code="invalid_orgnr")
    return brreg.lookup(orgnr, services.settings.brreg_url).__dict__


# ---------------------------------------------------------------------------
# Selskaper
# ---------------------------------------------------------------------------
class CompanyCreate(BaseModel):
    orgnr: str
    name: str = Field(min_length=1, max_length=200)
    org_form: Literal["ENK", "AS"] = "ENK"
    modules: list[Literal["taxi"]] = Field(default_factory=list)
    vat_registered: bool = True

    @field_validator("orgnr")
    @classmethod
    def _orgnr(cls, v: str) -> str:
        v = v.replace(" ", "")
        if not valid_orgnr(v):
            raise ValueError("Ugyldig organisasjonsnummer")
        return v


@router.post("/companies", status_code=201)
def create_company(body: CompanyCreate, principal: PrincipalDep, services: ServicesDep) -> dict:
    with services.db.tx(principal.user_id) as conn:
        cid = conn.execute(
            "select bokbuzz.create_company_v2(%s, %s, %s, %s, %s) as id",
            [body.orgnr, body.name, body.org_form, sorted(set(body.modules)), body.vat_registered],
        ).fetchone()["id"]
        return conn.execute("select * from bokbuzz.companies where id = %s", [cid]).fetchone()


@router.get("/companies")
def list_companies(principal: PrincipalDep, services: ServicesDep) -> list[dict]:
    with services.db.tx(principal.user_id) as conn:
        return conn.execute(
            "select c.*, m.role from bokbuzz.companies c join bokbuzz.company_members m"
            " on m.company_id = c.id and m.user_id = %s order by c.name", [principal.user_id]
        ).fetchall()


@router.get("/companies/{company_id}")
def get_company(ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        row = conn.execute("select * from bokbuzz.companies where id = %s", [ctx.company_id]).fetchone()
    return {**row, "role": ctx.role}


@router.get("/companies/{company_id}/accounts")
def list_accounts(ctx: CompanyDep, services: ServicesDep) -> list[dict]:
    with services.db.tx(ctx.user_id) as conn:
        return conn.execute("select * from bokbuzz.accounts where company_id = %s order by number",
                            [ctx.company_id]).fetchall()


@router.get("/companies/{company_id}/periods")
def list_periods(ctx: CompanyDep, services: ServicesDep) -> list[dict]:
    with services.db.tx(ctx.user_id) as conn:
        return conn.execute("select * from bokbuzz.periods where company_id = %s order by year, month",
                            [ctx.company_id]).fetchall()


@router.post("/companies/{company_id}/periods/{year}/{month}/close")
def close_period(year: int, month: int, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        ledger.close_period(conn, company_id=ctx.company_id, actor=ctx.user_id, year=year, month=month)
    return {"year": year, "month": month, "status": "closed"}


# ---------------------------------------------------------------------------
# Dokumenter
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/documents", status_code=201)
def upload_document(ctx: CompanyDep, services: ServicesDep, response: Response,
                    file: Annotated[UploadFile, File()]) -> dict:
    limit = services.settings.max_upload_bytes
    data = file.file.read(limit + 1)
    with services.db.tx(ctx.user_id) as conn:
        result = documents.upload_document(conn, services.storage, company_id=ctx.company_id,
                                           actor=ctx.user_id, data=data, filename=file.filename,
                                           max_bytes=limit)
    if not result.created:
        response.status_code = 200
    return {**result.document, "duplicate": not result.created}


@router.get("/companies/{company_id}/documents")
def list_documents(ctx: CompanyDep, services: ServicesDep,
                   status: Annotated[str | None, Query()] = None) -> list[dict]:
    with services.db.tx(ctx.user_id) as conn:
        return conn.execute(
            "select * from bokbuzz.documents where company_id = %s and (%s::text is null or status = %s)"
            " order by created_at desc limit 500", [ctx.company_id, status, status]
        ).fetchall()


@router.get("/companies/{company_id}/documents/{document_id}")
def get_document(document_id: UUID, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return documents.get_document(conn, ctx.company_id, document_id)


@router.get("/companies/{company_id}/documents/{document_id}/content")
def get_document_content(document_id: UUID, ctx: CompanyDep, services: ServicesDep) -> Response:
    with services.db.tx(ctx.user_id) as conn:
        data, mime = documents.read_content(conn, services.storage, ctx.company_id, document_id)
    return Response(content=data, media_type=mime,
                    headers={"content-disposition": f'inline; filename="{document_id}"'})


# ---------------------------------------------------------------------------
# Forslag og godkjenning (to klikk)
# ---------------------------------------------------------------------------
@router.get("/companies/{company_id}/proposals")
def list_proposals(ctx: CompanyDep, services: ServicesDep,
                   status: Annotated[str, Query(description="pending, approved, rejected,"
                                                " needs_manual eller all")] = "pending") -> list[dict]:
    status_filter = None if status in ("", "all") else status
    with services.db.tx(ctx.user_id) as conn:
        return conn.execute(
            "select * from bokbuzz.proposals where company_id = %s and (%s::text is null or status = %s)"
            " order by created_at limit 500", [ctx.company_id, status_filter, status_filter]
        ).fetchall()


@router.get("/companies/{company_id}/proposals/{proposal_id}")
def get_proposal(proposal_id: UUID, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        row = conn.execute("select * from bokbuzz.proposals where company_id = %s and id = %s",
                           [ctx.company_id, proposal_id]).fetchone()
        if not row:
            raise NotFound("Forslaget finnes ikke")
        doc = documents.get_document(conn, ctx.company_id, row["document_id"]) if row["document_id"] else None
        tx = conn.execute("select * from bokbuzz.bank_transactions where company_id = %s and id = %s",
                          [ctx.company_id, row["bank_transaction_id"]]).fetchone() \
            if row["bank_transaction_id"] else None
        names = {a["number"]: a["name"] for a in conn.execute(
            "select number, name from bokbuzz.accounts where company_id = %s", [ctx.company_id]).fetchall()}
    return {**row, "document": doc, "bank_transaction": tx, "account_names": names}


@router.post("/companies/{company_id}/proposals/{proposal_id}/review")
def open_review(proposal_id: UUID, ctx: CompanyDep, services: ServicesDep) -> dict:
    """Klikk 1: åpne forslaget ved siden av originalen."""
    with services.db.tx(ctx.user_id) as conn:
        return review.open_review(conn, company_id=ctx.company_id, proposal_id=proposal_id,
                                  actor=ctx.user_id, ttl_seconds=services.settings.review_token_ttl_seconds)


class ApproveBody(BaseModel):
    review_token: str = Field(min_length=10)
    confirm: Literal[True]
    corrected_draft: VoucherDraft | None = None


@router.post("/companies/{company_id}/proposals/{proposal_id}/approve")
def approve(proposal_id: UUID, body: ApproveBody, ctx: CompanyDep, services: ServicesDep) -> dict:
    """Klikk 2: bekreft og bokfør."""
    with services.db.tx(ctx.user_id) as conn:
        voucher = review.approve(conn, company_id=ctx.company_id, proposal_id=proposal_id,
                                 actor=ctx.user_id, review_token=body.review_token, confirm=body.confirm,
                                 corrected_draft=body.corrected_draft)
    return voucher.model_dump(mode="json")


class RejectBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/companies/{company_id}/proposals/{proposal_id}/reject")
def reject(proposal_id: UUID, body: RejectBody, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return review.reject(conn, company_id=ctx.company_id, proposal_id=proposal_id,
                             actor=ctx.user_id, reason=body.reason)


# ---------------------------------------------------------------------------
# Hovedbok
# ---------------------------------------------------------------------------
@router.get("/companies/{company_id}/vouchers")
def list_vouchers(ctx: CompanyDep, services: ServicesDep,
                  year: Annotated[int | None, Query()] = None) -> list[dict]:
    with services.db.tx(ctx.user_id) as conn:
        return conn.execute(
            "select * from bokbuzz.vouchers where company_id = %s and (%s::int is null or year = %s)"
            " order by year, series, number limit 2000", [ctx.company_id, year, year]
        ).fetchall()


@router.get("/companies/{company_id}/vouchers/{voucher_id}")
def get_voucher(voucher_id: UUID, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return ledger.load_voucher(conn, ctx.company_id, voucher_id).model_dump(mode="json")


class ReverseBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    voucher_date: date | None = None
    confirm: Literal[True]


@router.post("/companies/{company_id}/vouchers/{voucher_id}/reverse", status_code=201)
def reverse(voucher_id: UUID, body: ReverseBody, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        posted = ledger.reverse_voucher(conn, company_id=ctx.company_id, actor=ctx.user_id,
                                        voucher_id=voucher_id, reason=body.reason,
                                        voucher_date=body.voucher_date or oslo_today())
    return posted.model_dump(mode="json")


@router.get("/companies/{company_id}/reports/trial-balance")
def trial_balance(ctx: CompanyDep, services: ServicesDep,
                  date_from: Annotated[date, Query(alias="from")],
                  date_to: Annotated[date, Query(alias="to")]) -> dict:
    if date_to < date_from:
        raise ValidationFailed("Til-dato er før fra-dato")
    with services.db.tx(ctx.user_id) as conn:
        rows = ledger.trial_balance(conn, ctx.company_id, date_from, date_to)
    return {"from": date_from, "to": date_to, "accounts": rows,
            "total_ore": sum(r["balance_ore"] for r in rows)}


@router.get("/companies/{company_id}/audit/verify")
def verify_audit(ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        bad = audit.verify_chain(conn, ctx.company_id)
    if bad is not None:
        raise HTTPException(409, detail={"error": "audit_chain_broken", "first_bad_seq": bad})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Bank (kontoutskrift, avstemming)
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/bank/statements", status_code=201)
def import_bank_statement(ctx: CompanyDep, services: ServicesDep, response: Response,
                          file: Annotated[UploadFile, File()]) -> dict:
    """Importerer en CAMT.053-fil fra nettbanken. Avstemmingen kjører i bakgrunnen etterpå."""
    limit = services.settings.max_upload_bytes * 10
    data = file.file.read(limit + 1)
    with services.db.tx(ctx.user_id) as conn:
        results = bank.import_statement(conn, services.storage, company_id=ctx.company_id, actor=ctx.user_id,
                                        data=data, filename=file.filename, max_bytes=limit)
    if all(r["duplicate"] for r in results):
        response.status_code = 200
    return {"statements": results}


@router.get("/companies/{company_id}/bank/statements")
def list_bank_statements(ctx: CompanyDep, services: ServicesDep) -> list[dict]:
    with services.db.tx(ctx.user_id) as conn:
        return conn.execute(
            "select s.*, a.account_id from bokbuzz.bank_statements s"
            " join bokbuzz.bank_accounts a on a.id = s.bank_account_id"
            " where s.company_id = %s order by s.created_at desc limit 200", [ctx.company_id]).fetchall()


@router.get("/companies/{company_id}/bank/transactions")
def list_bank_transactions(ctx: CompanyDep, services: ServicesDep,
                           status: Annotated[Literal["matched", "suggested", "proposed", "missing_document"]
                                             | None, Query()] = None,
                           date_from: Annotated[date | None, Query(alias="from")] = None,
                           date_to: Annotated[date | None, Query(alias="to")] = None) -> list[dict]:
    with services.db.tx(ctx.user_id) as conn:
        return bank.list_transactions(conn, ctx.company_id, status, date_from, date_to)


@router.get("/companies/{company_id}/bank/reconciliation")
def bank_reconciliation(ctx: CompanyDep, services: ServicesDep) -> list[dict]:
    with services.db.tx(ctx.user_id) as conn:
        return bank.reconciliation_status(conn, ctx.company_id)


@router.post("/companies/{company_id}/bank/reconcile", status_code=202)
def request_bank_reconcile(ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        ledger.require_role(conn, ctx.company_id, ctx.user_id, ledger.POSTING_ROLES)
        bank.request_reconcile(conn, ctx.company_id, "manual", uuid4().hex)
    return {"queued": True}


class MatchDecision(BaseModel):
    accept: bool


@router.post("/companies/{company_id}/bank/matches/{match_id}")
def decide_bank_match(match_id: UUID, body: MatchDecision, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return bank.decide_match(conn, company_id=ctx.company_id, actor=ctx.user_id, match_id=match_id,
                                 accept=body.accept)


# ---------------------------------------------------------------------------
# MVA-melding (utkast; innsending kobles på når tilgangene er på plass)
# ---------------------------------------------------------------------------
@router.get("/companies/{company_id}/vat-returns/{year}/{term}")
def vat_return_draft(year: int, term: int, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        draft = vat_return.compute(conn, ctx.company_id, year, term)
    return {**draft, "submission_available": not isinstance(_vat_client(services), NotConfigured)}


@router.get("/companies/{company_id}/vat-returns/{year}/{term}/xml")
def vat_return_xml(year: int, term: int, ctx: CompanyDep, services: ServicesDep) -> Response:
    with services.db.tx(ctx.user_id) as conn:
        draft = vat_return.compute(conn, ctx.company_id, year, term)
    xml = vat_return.to_xml(draft, system_version="0.1.0", reference=f"{ctx.company_id}:{year}:{term}")
    return Response(content=xml, media_type="application/xml",
                    headers={"content-disposition": f'attachment; filename="mva-{year}-{term}.xml"'})


def _vat_client(services):
    return getattr(services, "vat_client", None) or NotConfigured()


# ---------------------------------------------------------------------------
# Lønn (L0)
# ---------------------------------------------------------------------------
class PayrollSettingsBody(BaseModel):
    aga_zone: Literal["1", "1a", "2", "3", "4", "4a", "5"] = "1"
    holiday_rate_bp: Literal[1020, 1200] = 1020
    pay_from_account: str = Field(pattern=r"^[0-9]{11}$")
    tax_withholding_account: str | None = Field(default=None, pattern=r"^[0-9]{11}$")
    kid_withholding: str | None = Field(default=None, pattern=r"^[0-9]{2,25}$")
    kid_aga: str | None = Field(default=None, pattern=r"^[0-9]{2,25}$")
    tax_authority_account: str | None = Field(default=None, pattern=r"^[0-9]{11}$")


@router.get("/companies/{company_id}/payroll/settings")
def get_payroll_settings(ctx: CompanyDep, services: ServicesDep) -> dict | None:
    with services.db.tx(ctx.user_id) as conn:
        ledger.require_role(conn, ctx.company_id, ctx.user_id, payroll.PAYROLL_ROLES)
        return payroll.get_settings(conn, ctx.company_id)


@router.put("/companies/{company_id}/payroll/settings")
def put_payroll_settings(body: PayrollSettingsBody, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.save_settings(conn, company_id=ctx.company_id, actor=ctx.user_id, data=body.model_dump())


class EmployeeBody(BaseModel):
    national_id: str = Field(pattern=r"^[0-9]{11}$")
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    bank_account: str = Field(pattern=r"^[0-9]{11}$")
    position_pct_bp: int = Field(default=10000, ge=1, le=10000)
    pay_type: Literal["monthly", "hourly"]
    monthly_salary_ore: int | None = Field(default=None, gt=0, le=10**10)
    hourly_rate_ore: int | None = Field(default=None, gt=0, le=10**8)
    tax_card_kind: Literal["percent", "table", "none"] = "percent"
    tax_percent: int | None = Field(default=None, ge=0, le=100)
    tax_table: str | None = Field(default=None, pattern=r"^[0-9]{4}$")
    start_date: date
    end_date: date | None = None


@router.get("/companies/{company_id}/employees")
def list_employees(ctx: CompanyDep, services: ServicesDep) -> list[dict]:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.list_employees(conn, ctx.company_id, ctx.user_id)


@router.post("/companies/{company_id}/employees", status_code=201)
def create_employee(body: EmployeeBody, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.create_employee(conn, company_id=ctx.company_id, actor=ctx.user_id, data=body.model_dump())


@router.put("/companies/{company_id}/employees/{employee_id}")
def update_employee(employee_id: UUID, body: EmployeeBody, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.update_employee(conn, company_id=ctx.company_id, actor=ctx.user_id,
                                       employee_id=employee_id, data=body.model_dump())


class RunCreate(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    pay_date: date


@router.get("/companies/{company_id}/payroll/runs")
def list_payroll_runs(ctx: CompanyDep, services: ServicesDep) -> list[dict]:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.list_runs(conn, ctx.company_id, ctx.user_id)


@router.post("/companies/{company_id}/payroll/runs", status_code=201)
def create_payroll_run(body: RunCreate, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        run = payroll.create_run(conn, company_id=ctx.company_id, actor=ctx.user_id, year=body.year,
                                 month=body.month, pay_date=body.pay_date)
        return payroll.summary(conn, ctx.company_id, run["id"])


@router.get("/companies/{company_id}/payroll/runs/{run_id}")
def get_payroll_run(run_id: UUID, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        ledger.require_role(conn, ctx.company_id, ctx.user_id, payroll.PAYROLL_ROLES)
        return payroll.summary(conn, ctx.company_id, run_id)


class LineBody(BaseModel):
    hours_x100: int | None = Field(default=None, ge=0, le=100_000)
    bonus_ore: int = Field(default=0, ge=0, le=10**10)
    base_override_ore: int | None = Field(default=None, ge=0, le=10**10)
    tax_override_ore: int | None = Field(default=None, ge=0, le=10**10)
    note: str | None = Field(default=None, max_length=300)


@router.post("/companies/{company_id}/payroll/runs/{run_id}/lines/{employee_id}")
def update_payroll_line(run_id: UUID, employee_id: UUID, body: LineBody, ctx: CompanyDep,
                        services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.update_line(
            conn, company_id=ctx.company_id, actor=ctx.user_id, run_id=run_id, employee_id=employee_id,
            inp=payroll_calc.LineInput(body.hours_x100, body.bonus_ore, body.base_override_ore,
                                       body.tax_override_ore), note=body.note)


class RunApprove(BaseModel):
    content_hash: str = Field(min_length=10)
    confirm: Literal[True]


@router.post("/companies/{company_id}/payroll/runs/{run_id}/approve")
def approve_payroll_run(run_id: UUID, body: RunApprove, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.approve_run(conn, company_id=ctx.company_id, actor=ctx.user_id, run_id=run_id,
                                   content_hash_seen=body.content_hash, confirm=body.confirm)


@router.post("/companies/{company_id}/payroll/runs/{run_id}/cancel")
def cancel_payroll_run(run_id: UUID, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.cancel_run(conn, company_id=ctx.company_id, actor=ctx.user_id, run_id=run_id)


@router.get("/companies/{company_id}/payroll/runs/{run_id}/payment-file")
def payroll_payment_file(run_id: UUID, ctx: CompanyDep, services: ServicesDep) -> Response:
    with services.db.tx(ctx.user_id) as conn:
        xml = payroll.payment_file(conn, company_id=ctx.company_id, actor=ctx.user_id, run_id=run_id)
    return Response(content=xml, media_type="application/xml",
                    headers={"content-disposition": f'attachment; filename="lonn-{run_id}.xml"'})


@router.get("/companies/{company_id}/payroll/runs/{run_id}/payslips/{employee_id}")
def payroll_payslip(run_id: UUID, employee_id: UUID, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.payslip(conn, company_id=ctx.company_id, actor=ctx.user_id, run_id=run_id,
                               employee_id=employee_id)


@router.get("/companies/{company_id}/payroll/terms/{year}/{term}")
def payroll_term(year: int, term: int, ctx: CompanyDep, services: ServicesDep) -> dict:
    with services.db.tx(ctx.user_id) as conn:
        return payroll.term_payments(conn, company_id=ctx.company_id, actor=ctx.user_id, year=year, term=term)


@router.get("/companies/{company_id}/payroll/terms/{year}/{term}/payment-file")
def payroll_term_file(year: int, term: int, ctx: CompanyDep, services: ServicesDep,
                      kind: Annotated[Literal["withholding", "aga"], Query()]) -> Response:
    with services.db.tx(ctx.user_id) as conn:
        xml = payroll.term_payment_file(conn, company_id=ctx.company_id, actor=ctx.user_id, year=year,
                                        term=term, kind=kind)
    return Response(content=xml, media_type="application/xml",
                    headers={"content-disposition": f'attachment; filename="{kind}-{year}-{term}.xml"'})
