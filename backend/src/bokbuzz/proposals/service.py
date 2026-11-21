"""Lager konteringsforslag fra et dokument. Forslaget bokføres aldri herfra;
det havner i godkjenningskøen."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import ValidationError

from .. import audit
from ..ai.base import ModelRequest, ModelRouter, SuggestionModel
from ..db import Conn
from ..documents.service import read_content
from ..documents.storage import DocumentStorage
from ..errors import DomainError, NotFound
from ..ledger.models import DraftLine, VoucherDraft, content_hash
from ..ledger.money import oslo_today
from ..ledger.service import expand_lines, rules_version
from .prompt import PROMPT_VERSION, SYSTEM, build_prompt
from .schema import Extraction, response_schema
from .validation import Finding, validate

PAYMENT_ACCOUNTS = {"bank": "1920", "private": "2070", "cash": "1900", "unpaid": "2400", "unknown": "1920"}


def _vat_rates_on(conn: Conn, on: date) -> dict[str, tuple[int, str]]:
    rows = conn.execute(
        "select r.code, r.rate_bp, c.direction, c.description from bokbuzz.vat_rates r"
        " join bokbuzz.vat_codes c on c.code = r.code"
        " where r.valid_from <= %s and (r.valid_to is null or r.valid_to >= %s) order by r.code",
        [on, on],
    ).fetchall()
    return {r["code"]: (r["rate_bp"], r["direction"]) for r in rows}


def _accounts(conn: Conn, company_id: UUID, on: date) -> list[dict]:
    return conn.execute(
        "select number, name, account_type, default_vat_code from bokbuzz.accounts"
        " where company_id = %s and active_from <= %s and (active_to is null or active_to >= %s)"
        " order by number",
        [company_id, on, on],
    ).fetchall()


def _run_model(
    model: SuggestionModel, request: ModelRequest, conn: Conn, company_id: UUID, accounts: dict, today: date
) -> tuple[Extraction | None, list[Finding], list[Finding], dict]:
    resp = model.generate(request)
    try:
        ex = Extraction.model_validate_json(resp.text)
    except ValidationError as exc:
        return None, [Finding("invalid_output", f"Ugyldig svar fra modellen: {exc.error_count()} feil",
                              escalate=True)], [], resp.usage
    rates = _vat_rates_on(conn, ex.document_date or today)
    errors, warnings = validate(ex, accounts=accounts, vat_rates=rates, today=today)
    return ex, errors, warnings, resp.usage


def build_draft(ex: Extraction) -> VoucherDraft:
    assert ex.document_date is not None
    lines = [DraftLine(account=ln.account, amount_ore=ln.net_amount_ore, vat_code=ln.vat_code,
                       vat_amount_ore=ln.vat_amount_ore, description=ln.description[:300] or None)
             for ln in ex.lines]
    lines.append(DraftLine(account=PAYMENT_ACCOUNTS[ex.payment], amount_ore=-ex.total_amount_ore,
                           description=f"Betalt ({ex.payment})"))
    desc = " – ".join(p for p in [ex.supplier_name, ex.lines[0].description] if p) or "Bilag"
    return VoucherDraft(voucher_date=ex.document_date, description=desc[:500], lines=lines)


def generate_proposal(
    conn: Conn, storage: DocumentStorage, router: ModelRouter, *, company_id: UUID, document_id: UUID
) -> dict:
    doc = conn.execute(
        "select * from bokbuzz.documents where company_id = %s and id = %s for update",
        [company_id, document_id],
    ).fetchone()
    if not doc:
        raise NotFound("Dokumentet finnes ikke")
    today = oslo_today()
    rv = rules_version(conn, company_id)
    input_hash = hashlib.sha256(
        "|".join([doc["sha256"], PROMPT_VERSION, rv, router.default.name, router.escalation.name]).encode()
    ).hexdigest()
    existing = conn.execute(
        "select * from bokbuzz.proposals where document_id = %s and input_hash = %s",
        [document_id, input_hash],
    ).fetchone()
    if existing:
        return existing

    content, mime = read_content(conn, storage, company_id, document_id)
    account_rows = _accounts(conn, company_id, today)
    accounts = {a["number"]: a for a in account_rows}
    vat_list = [{"code": c, "rate_bp": r, "description": ""} for c, (r, _d) in _vat_rates_on(conn, today).items()]
    request = ModelRequest(system=SYSTEM, prompt=build_prompt(account_rows, vat_list), content=content,
                           mime_type=mime, response_schema=response_schema())

    model = router.default
    ex, errors, warnings, usage = _run_model(model, request, conn, company_id, accounts, today)
    usage_all = {model.name: usage}
    escalated = False
    if any(f.escalate for f in errors) or (ex is not None and ex.ambiguous):
        escalated = True
        model = router.escalation
        ex, errors, warnings, usage = _run_model(model, request, conn, company_id, accounts, today)
        usage_all[model.name] = usage

    draft: VoucherDraft | None = None
    if ex is not None and not errors:
        draft = build_draft(ex)
        try:
            expand_lines(conn, company_id, draft)
        except DomainError as exc:
            errors.append(Finding(exc.code, exc.message))
            draft = None

    status = "pending" if draft is not None else "needs_manual"
    row = conn.execute(
        "insert into bokbuzz.proposals (company_id, document_id, status, model, prompt_version, rules_version,"
        " input_hash, extraction, draft, draft_hash, validation_errors, warnings, escalated, usage)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " on conflict (document_id, input_hash) do nothing returning *",
        [company_id, document_id, status, model.name, PROMPT_VERSION, rv, input_hash,
         Jsonb(json.loads(ex.model_dump_json())) if ex else None,
         Jsonb(draft.model_dump(mode="json")) if draft else None,
         content_hash(draft) if draft else None,
         Jsonb([f.as_dict() for f in errors]), Jsonb([f.as_dict() for f in warnings]), escalated,
         Jsonb(usage_all)],
    ).fetchone()
    if row is None:
        return conn.execute(
            "select * from bokbuzz.proposals where document_id = %s and input_hash = %s",
            [document_id, input_hash],
        ).fetchone()
    if doc["status"] == "received":
        conn.execute("update bokbuzz.documents set status = 'extracted' where id = %s", [document_id])
        conn.execute("update bokbuzz.documents set status = 'proposed' where id = %s", [document_id])
    elif doc["status"] == "extracted":
        conn.execute("update bokbuzz.documents set status = 'proposed' where id = %s", [document_id])
    audit.record(conn, company_id=company_id, actor=None, event_type="proposal.created",
                 entity_type="proposal", entity_id=row["id"],
                 payload={"document_id": str(document_id), "status": status, "model": model.name,
                          "prompt_version": PROMPT_VERSION, "rules_version": rv, "input_hash": input_hash,
                          "escalated": escalated})
    return row


def extract_document_job(storage: DocumentStorage, router: ModelRouter):
    """Handler for jobbkøen."""

    def handler(conn: Conn, job: dict) -> None:
        generate_proposal(conn, storage, router, company_id=job["company_id"],
                          document_id=UUID(job["payload"]["document_id"]))

    return handler
