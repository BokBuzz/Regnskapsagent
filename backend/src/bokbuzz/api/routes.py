"""HTTP-ruter. Alle selskapsruter ligger under /companies/{company_id} og går
gjennom get_company, som krever medlemskap."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from .. import audit, brreg
from ..documents import service as documents
from ..errors import NotFound, ValidationFailed
from ..ledger import service as ledger
from ..ledger.models import VoucherDraft
from ..ledger.money import oslo_today
from ..proposals.validation import valid_orgnr
from ..review import service as review
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
        doc = documents.get_document(conn, ctx.company_id, row["document_id"])
    return {**row, "document": doc}


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
