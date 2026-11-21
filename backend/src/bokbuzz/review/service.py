"""Godkjenning i to klikk.

Klikk 1 (open_review): brukeren åpner forslaget ved siden av originalen. Det
gir et engangs-token knyttet til bruker, forslag og innholdet som ble vist.
Klikk 2 (approve): brukeren bekrefter med tokenet. Først da opprettes en
godkjenning, og hovedboken bokfører.

Det finnes ingen massegodkjenning, og ingen kodevei bokfører et forslag uten
begge stegene."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from .. import audit
from ..db import Conn
from ..errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..ledger.models import PostedVoucher, VoucherDraft, content_hash
from ..ledger.service import (
    POSTING_ROLES,
    create_approval,
    load_voucher,
    post_voucher,
    require_role,
    rules_version,
)

NO_DRAFT = "none"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _proposal_for_update(conn: Conn, company_id: UUID, proposal_id: UUID) -> dict:
    row = conn.execute(
        "select * from bokbuzz.proposals where company_id = %s and id = %s for update",
        [company_id, proposal_id],
    ).fetchone()
    if not row:
        raise NotFound("Forslaget finnes ikke")
    return row


def open_review(
    conn: Conn, *, company_id: UUID, proposal_id: UUID, actor: UUID, ttl_seconds: int
) -> dict:
    require_role(conn, company_id, actor, POSTING_ROLES)
    proposal = _proposal_for_update(conn, company_id, proposal_id)
    if proposal["status"] not in ("pending", "needs_manual"):
        raise Conflict("Forslaget er allerede behandlet", code="proposal_decided")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    session = conn.execute(
        "insert into bokbuzz.review_sessions (company_id, proposal_id, user_id, token_hash, draft_hash,"
        " expires_at) values (%s, %s, %s, %s, %s, %s) returning id, expires_at",
        [company_id, proposal_id, actor, _hash_token(token), proposal["draft_hash"] or NO_DRAFT, expires],
    ).fetchone()
    audit.record(conn, company_id=company_id, actor=actor, event_type="proposal.review_opened",
                 entity_type="proposal", entity_id=proposal_id,
                 payload={"review_session_id": str(session["id"])})
    return {"review_token": token, "expires_at": session["expires_at"], "proposal": proposal}


def approve(
    conn: Conn,
    *,
    company_id: UUID,
    proposal_id: UUID,
    actor: UUID,
    review_token: str,
    confirm: bool,
    corrected_draft: VoucherDraft | None = None,
) -> PostedVoucher:
    if confirm is not True:
        raise ValidationFailed("Godkjenning må bekreftes eksplisitt", code="confirm_required")
    require_role(conn, company_id, actor, POSTING_ROLES)
    proposal = _proposal_for_update(conn, company_id, proposal_id)

    session = conn.execute(
        "select * from bokbuzz.review_sessions where company_id = %s and token_hash = %s for update",
        [company_id, _hash_token(review_token)],
    ).fetchone()
    if (not session or session["proposal_id"] != proposal_id or session["user_id"] != actor):
        raise Forbidden("Forslaget må åpnes til gjennomgang av samme bruker før godkjenning",
                        code="review_required")
    if session["used_at"] is not None:
        raise Conflict("Gjennomgangen er allerede brukt", code="review_used")
    if session["expires_at"] < datetime.now(UTC):
        raise Conflict("Gjennomgangen har utløpt; åpne forslaget på nytt", code="review_expired")
    if proposal["status"] not in ("pending", "needs_manual"):
        raise Conflict("Forslaget er allerede behandlet", code="proposal_decided")
    if (proposal["draft_hash"] or NO_DRAFT) != session["draft_hash"]:
        raise Conflict("Forslaget er endret siden det ble åpnet", code="proposal_changed")
    if proposal["rules_version"] != rules_version(conn, company_id):
        raise Conflict("Kontoplan eller MVA-regler er endret; forslaget må lages på nytt",
                       code="rules_changed")

    if corrected_draft is not None:
        final = corrected_draft
    elif proposal["draft"] is not None:
        final = VoucherDraft.model_validate(proposal["draft"])
    else:
        raise ValidationFailed("Forslaget mangler kontering og må rettes før godkjenning",
                               code="draft_required")
    corrected = corrected_draft is not None and content_hash(final) != proposal["draft_hash"]

    conn.execute("update bokbuzz.review_sessions set used_at = now() where id = %s", [session["id"]])
    approval_id = create_approval(conn, company_id=company_id, actor=actor, kind="proposal", request=final,
                                  proposal_id=proposal_id, review_session_id=session["id"])
    conn.execute("update bokbuzz.documents set status = 'approved' where company_id = %s and id = %s",
                 [company_id, proposal["document_id"]])
    voucher = post_voucher(conn, company_id=company_id, actor=actor, request=final,
                           approval_id=approval_id, idempotency_key=f"proposal:{proposal_id}",
                           document_id=proposal["document_id"])
    conn.execute("update bokbuzz.documents set status = 'posted' where company_id = %s and id = %s",
                 [company_id, proposal["document_id"]])
    conn.execute(
        "update bokbuzz.proposals set status = 'approved', decided_by = %s, decided_at = now(),"
        " decision_note = %s, voucher_id = %s where id = %s",
        [actor, "rettet av bruker" if corrected else None, voucher.id, proposal_id],
    )
    return voucher


def reject(conn: Conn, *, company_id: UUID, proposal_id: UUID, actor: UUID, reason: str) -> dict:
    require_role(conn, company_id, actor, POSTING_ROLES)
    proposal = _proposal_for_update(conn, company_id, proposal_id)
    if proposal["status"] not in ("pending", "needs_manual"):
        raise Conflict("Forslaget er allerede behandlet", code="proposal_decided")
    row = conn.execute(
        "update bokbuzz.proposals set status = 'rejected', decided_by = %s, decided_at = now(),"
        " decision_note = %s where id = %s returning *",
        [actor, reason[:500], proposal_id],
    ).fetchone()
    conn.execute(
        "update bokbuzz.documents set status = 'extracted' where company_id = %s and id = %s"
        " and status = 'proposed'",
        [company_id, proposal["document_id"]],
    )
    audit.record(conn, company_id=company_id, actor=actor, event_type="proposal.rejected",
                 entity_type="proposal", entity_id=proposal_id, payload={"reason": reason[:500]})
    return row


def get_posted_for_proposal(conn: Conn, company_id: UUID, proposal: dict) -> PostedVoucher | None:
    if proposal.get("voucher_id"):
        return load_voucher(conn, company_id, proposal["voucher_id"])
    return None
