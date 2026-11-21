"""Hovedboken. post_voucher er eneste vei inn i hovedboken.

Alt skjer i transaksjonen til forbindelsen som sendes inn. Kalleren eier
transaksjonen (db.tx), slik at bokføring, statusendringer og revisjonslogg
committes samlet eller ikke i det hele tatt."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from uuid import UUID

from .. import audit
from ..db import Conn
from ..errors import Conflict, Forbidden, NotFound, ValidationFailed
from .models import (
    PostedVoucher,
    PostingLine,
    ReversalRequest,
    VoucherDraft,
    content_hash,
)
from .money import vat_amount

POSTING_ROLES = frozenset({"owner", "accountant"})
DEFAULT_SERIES = "B"
REVERSAL_SERIES = "R"
VAT_TOLERANCE_ORE = 1  # avvik per linje mellom oppgitt og beregnet MVA (verifiser med regnskapsfører)


# ---------------------------------------------------------------------------
# Oppslag
# ---------------------------------------------------------------------------
def member_role(conn: Conn, company_id: UUID, user_id: UUID) -> str | None:
    row = conn.execute(
        "select role from bokbuzz.company_members where company_id = %s and user_id = %s",
        [company_id, user_id],
    ).fetchone()
    return row["role"] if row else None


def require_role(conn: Conn, company_id: UUID, user_id: UUID, roles: frozenset[str]) -> str:
    role = member_role(conn, company_id, user_id)
    if role not in roles:
        raise Forbidden("Brukeren har ikke rettighet til dette i selskapet")
    return role


def rules_version(conn: Conn, company_id: UUID) -> str:
    """Hash av kontoplan og MVA-satser. Endres de, blir eldre forslag ugyldige."""
    accounts = conn.execute(
        "select number, account_type, default_vat_code, active_from, active_to"
        " from bokbuzz.accounts where company_id = %s order by number",
        [company_id],
    ).fetchall()
    rates = conn.execute(
        "select code, rate_bp, valid_from, valid_to from bokbuzz.vat_rates order by code, valid_from"
    ).fetchall()
    blob = json.dumps({"accounts": accounts, "rates": rates}, default=str, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def vat_rate_on(conn: Conn, code: str, on: date) -> tuple[int, str, str | None]:
    """Returnerer (sats i basispunkter, retning, MVA-konto) for koden på datoen."""
    row = conn.execute(
        "select r.rate_bp, c.direction, c.ledger_account from bokbuzz.vat_rates r"
        " join bokbuzz.vat_codes c on c.code = r.code"
        " where r.code = %s and r.valid_from <= %s and (r.valid_to is null or r.valid_to >= %s)",
        [code, on, on],
    ).fetchone()
    if not row:
        raise ValidationFailed(f"MVA-kode {code} er ikke gyldig {on.isoformat()}", code="invalid_vat_code")
    return row["rate_bp"], row["direction"], row["ledger_account"]


def _active_accounts(conn: Conn, company_id: UUID, numbers: set[str], on: date) -> set[str]:
    rows = conn.execute(
        "select number from bokbuzz.accounts where company_id = %s and number = any(%s)"
        " and active_from <= %s and (active_to is null or active_to >= %s)",
        [company_id, list(numbers), on, on],
    ).fetchall()
    return {r["number"] for r in rows}


# ---------------------------------------------------------------------------
# Linjer og MVA
# ---------------------------------------------------------------------------
def expand_lines(conn: Conn, company_id: UUID, draft: VoucherDraft) -> list[PostingLine]:
    """Gjør godkjente linjer om til hovedbokslinjer, med MVA-linjer beregnet
    deterministisk per linje. Sjekker kontoer, koder og balanse."""
    out: list[PostingLine] = []
    for src in draft.lines:
        base_no = len(out) + 1
        out.append(PostingLine(line_no=base_no, account=src.account, amount_ore=src.amount_ore,
                               vat_code=src.vat_code, description=src.description))
        if src.vat_code is None:
            if src.vat_amount_ore:
                raise ValidationFailed("MVA-beløp uten MVA-kode", code="vat_without_code")
            continue
        rate_bp, direction, vat_account = vat_rate_on(conn, src.vat_code, draft.voucher_date)
        computed = vat_amount(src.amount_ore, rate_bp) if direction != "none" else 0
        vat = computed
        if src.vat_amount_ore is not None:
            if abs(src.vat_amount_ore - computed) > VAT_TOLERANCE_ORE:
                raise ValidationFailed(
                    f"MVA på linje {base_no} er {src.vat_amount_ore} øre, forventet {computed} øre",
                    code="vat_mismatch",
                )
            vat = src.vat_amount_ore
        if vat != 0:
            assert vat_account is not None
            out.append(PostingLine(line_no=len(out) + 1, account=vat_account, amount_ore=vat,
                                   vat_code=src.vat_code, vat_base_line_no=base_no,
                                   description=f"MVA {src.vat_code}"))
    _check_lines(conn, company_id, draft.voucher_date, out)
    return out


def _check_lines(conn: Conn, company_id: UUID, on: date, lines: list[PostingLine]) -> None:
    if len(lines) < 2:
        raise ValidationFailed("Et bilag må ha minst to linjer", code="too_few_lines")
    total = sum(line.amount_ore for line in lines)
    if total != 0:
        raise ValidationFailed(f"Bilaget er ikke i balanse (differanse {total} øre)", code="unbalanced")
    numbers = {line.account for line in lines}
    missing = numbers - _active_accounts(conn, company_id, numbers, on)
    if missing:
        raise ValidationFailed(
            f"Kontoer finnes ikke eller er ikke aktive {on.isoformat()}: {', '.join(sorted(missing))}",
            code="inactive_account",
        )


# ---------------------------------------------------------------------------
# Bokføring
# ---------------------------------------------------------------------------
def post_voucher(
    conn: Conn,
    *,
    company_id: UUID,
    actor: UUID,
    request: VoucherDraft | ReversalRequest,
    approval_id: UUID,
    idempotency_key: str,
    document_id: UUID | None = None,
) -> PostedVoucher:
    """Bokfører et godkjent bilag. Rekkefølgen følger designdokumentet:
    idempotens, lås dokument, rolle og godkjenning, åpen periode, kontoer og
    MVA, balanse, bilagsnummer, skriving. Databasen sjekker balanse, periode og
    uforanderlighet en gang til ved commit."""
    chash = content_hash(request)

    # 1. Idempotens
    conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                 [f"voucher:{company_id}:{idempotency_key}"])
    existing = conn.execute(
        "select id, content_hash from bokbuzz.vouchers where company_id = %s and idempotency_key = %s",
        [company_id, idempotency_key],
    ).fetchone()
    if existing:
        if existing["content_hash"] != chash:
            raise Conflict("Idempotensnøkkelen er brukt med annet innhold", code="idempotency_conflict")
        voucher = load_voucher(conn, company_id, existing["id"])
        return voucher.model_copy(update={"created": False})

    # 2. Lås kildedokumentet
    if document_id is not None:
        doc = conn.execute(
            "select id, status from bokbuzz.documents where company_id = %s and id = %s for update",
            [company_id, document_id],
        ).fetchone()
        if not doc:
            raise NotFound("Dokumentet finnes ikke")
        if _active_voucher_for_document(conn, company_id, document_id):
            raise Conflict("Dokumentet er allerede bokført", code="already_posted")

    # 3. Rolle og godkjenning
    require_role(conn, company_id, actor, POSTING_ROLES)
    approval = conn.execute(
        "select * from bokbuzz.approvals where company_id = %s and id = %s for update",
        [company_id, approval_id],
    ).fetchone()
    if not approval:
        raise Forbidden("Godkjenningen finnes ikke", code="approval_missing")
    if approval["used_at"] is not None:
        raise Conflict("Godkjenningen er allerede brukt", code="approval_used")
    if approval["approved_by"] != actor:
        raise Forbidden("Godkjenningen tilhører en annen bruker", code="approval_wrong_user")
    if approval["content_hash"] != chash:
        raise Conflict("Innholdet er endret etter godkjenning", code="approval_mismatch")
    expected = {"reversal"} if isinstance(request, ReversalRequest) else {"proposal", "manual"}
    if approval["kind"] not in expected:
        raise Forbidden("Feil type godkjenning", code="approval_kind")
    if document_id is not None:
        # Et dokument kan bare bokføres via sitt eget forslag, altså etter gjennomgang i to klikk.
        linked = conn.execute(
            "select 1 from bokbuzz.proposals where company_id = %s and id = %s and document_id = %s",
            [company_id, approval["proposal_id"], document_id],
        ).fetchone() if approval["kind"] == "proposal" else None
        if not linked:
            raise Forbidden("Dokumentet kan bare bokføres via godkjent forslag", code="approval_document")

    # 4–6. Periode, kontoer, MVA og balanse
    if isinstance(request, ReversalRequest):
        lines, description, reverses = _reversal_lines(conn, company_id, request)
        series = REVERSAL_SERIES
    else:
        lines = expand_lines(conn, company_id, request)
        description, reverses, series = request.description, None, DEFAULT_SERIES
    voucher_date = request.voucher_date
    _require_open_period(conn, company_id, voucher_date)

    # 7. Bilagsnummer fra låst teller (ruller tilbake sammen med transaksjonen, så ingen hull)
    year = voucher_date.year
    number = conn.execute(
        "insert into bokbuzz.voucher_counters as c (company_id, year, series, next_number)"
        " values (%s, %s, %s, 2)"
        " on conflict (company_id, year, series) do update set next_number = c.next_number + 1"
        " returning next_number - 1 as number",
        [company_id, year, series],
    ).fetchone()["number"]

    # 8. Skriv bilag, linjer, godkjenning og revisjonshendelse
    voucher_id = conn.execute(
        "insert into bokbuzz.vouchers (company_id, year, series, number, voucher_date, description,"
        " document_id, idempotency_key, content_hash, approval_id, reverses_voucher_id, reversal_reason,"
        " posted_by, line_count)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        [company_id, year, series, number, voucher_date, description, document_id, idempotency_key,
         chash, approval_id, reverses,
         request.reason if isinstance(request, ReversalRequest) else None, actor, len(lines)],
    ).fetchone()["id"]
    with conn.cursor() as cur:
        cur.executemany(
            "insert into bokbuzz.voucher_lines (voucher_id, company_id, line_no, account_number, amount_ore,"
            " vat_code, vat_base_line_no, description) values (%s, %s, %s, %s, %s, %s, %s, %s)",
            [(voucher_id, company_id, ln.line_no, ln.account, ln.amount_ore, ln.vat_code,
              ln.vat_base_line_no, ln.description) for ln in lines],
        )
    conn.execute("update bokbuzz.approvals set used_at = now() where id = %s", [approval_id])
    audit.record(
        conn, company_id=company_id, actor=actor, event_type="voucher.posted",
        entity_type="voucher", entity_id=voucher_id,
        payload={"series": series, "number": number, "year": year, "content_hash": chash,
                 "document_id": str(document_id) if document_id else None,
                 "reverses": str(reverses) if reverses else None,
                 "lines": [[ln.account, ln.amount_ore, ln.vat_code] for ln in lines]},
    )
    return PostedVoucher(
        id=voucher_id, company_id=company_id, year=year, series=series, number=number,
        voucher_date=voucher_date, description=description, document_id=document_id,
        reverses_voucher_id=reverses, lines=lines,
    )


def _require_open_period(conn: Conn, company_id: UUID, on: date) -> None:
    row = conn.execute(
        "select status from bokbuzz.periods where company_id = %s and year = %s and month = %s",
        [company_id, on.year, on.month],
    ).fetchone()
    if not row or row["status"] != "open":
        raise Conflict(f"Perioden {on.year}-{on.month:02d} er ikke åpen", code="period_closed")


def _active_voucher_for_document(conn: Conn, company_id: UUID, document_id: UUID) -> UUID | None:
    row = conn.execute(
        "select v.id from bokbuzz.vouchers v where v.company_id = %s and v.document_id = %s"
        " and v.reverses_voucher_id is null"
        " and not exists (select 1 from bokbuzz.vouchers r where r.reverses_voucher_id = v.id)",
        [company_id, document_id],
    ).fetchone()
    return row["id"] if row else None


def _reversal_lines(
    conn: Conn, company_id: UUID, req: ReversalRequest
) -> tuple[list[PostingLine], str, UUID]:
    original = conn.execute(
        "select * from bokbuzz.vouchers where company_id = %s and id = %s",
        [company_id, req.reverses_voucher_id],
    ).fetchone()
    if not original:
        raise NotFound("Bilaget som skal reverseres finnes ikke")
    if original["reverses_voucher_id"] is not None:
        raise Conflict("Et reverseringsbilag kan ikke reverseres", code="reverse_reversal")
    already = conn.execute(
        "select 1 from bokbuzz.vouchers where reverses_voucher_id = %s", [original["id"]]
    ).fetchone()
    if already:
        raise Conflict("Bilaget er allerede reversert", code="already_reversed")
    if req.voucher_date < original["voucher_date"]:
        raise ValidationFailed("Reversering kan ikke dateres før originalen", code="reversal_date")
    src = conn.execute(
        "select * from bokbuzz.voucher_lines where voucher_id = %s order by line_no", [original["id"]]
    ).fetchall()
    lines = [
        PostingLine(line_no=r["line_no"], account=r["account_number"], amount_ore=-r["amount_ore"],
                    vat_code=r["vat_code"], vat_base_line_no=r["vat_base_line_no"],
                    description=r["description"])
        for r in src
    ]
    _check_lines(conn, company_id, req.voucher_date, lines)
    desc = f"Reversering av {original['series']}{original['number']}/{original['year']}: {req.reason}"
    return lines, desc[:500], original["id"]


def create_approval(
    conn: Conn,
    *,
    company_id: UUID,
    actor: UUID,
    kind: str,
    request: VoucherDraft | ReversalRequest,
    proposal_id: UUID | None = None,
    review_session_id: UUID | None = None,
) -> UUID:
    require_role(conn, company_id, actor, POSTING_ROLES)
    row = conn.execute(
        "insert into bokbuzz.approvals (company_id, kind, proposal_id, review_session_id, approved_by,"
        " content_hash) values (%s, %s, %s, %s, %s, %s) returning id",
        [company_id, kind, proposal_id, review_session_id, actor, content_hash(request)],
    ).fetchone()
    audit.record(conn, company_id=company_id, actor=actor, event_type="approval.created",
                 entity_type="approval", entity_id=row["id"],
                 payload={"kind": kind, "proposal_id": str(proposal_id) if proposal_id else None,
                          "content_hash": content_hash(request)})
    return row["id"]


def reverse_voucher(
    conn: Conn, *, company_id: UUID, actor: UUID, voucher_id: UUID, reason: str, voucher_date: date
) -> PostedVoucher:
    req = ReversalRequest(reverses_voucher_id=voucher_id, reason=reason, voucher_date=voucher_date)
    approval_id = create_approval(conn, company_id=company_id, actor=actor, kind="reversal", request=req)
    original = load_voucher(conn, company_id, voucher_id)
    posted = post_voucher(conn, company_id=company_id, actor=actor, request=req, approval_id=approval_id,
                          idempotency_key=f"reversal:{voucher_id}")
    if original.document_id:
        conn.execute(
            "update bokbuzz.documents set status = 'approved' where company_id = %s and id = %s"
            " and status = 'posted'",
            [company_id, original.document_id],
        )
    return posted


# ---------------------------------------------------------------------------
# Lesing og perioder
# ---------------------------------------------------------------------------
def load_voucher(conn: Conn, company_id: UUID, voucher_id: UUID) -> PostedVoucher:
    v = conn.execute(
        "select * from bokbuzz.vouchers where company_id = %s and id = %s", [company_id, voucher_id]
    ).fetchone()
    if not v:
        raise NotFound("Bilaget finnes ikke")
    lines = conn.execute(
        "select * from bokbuzz.voucher_lines where voucher_id = %s order by line_no", [voucher_id]
    ).fetchall()
    return PostedVoucher(
        id=v["id"], company_id=v["company_id"], year=v["year"], series=v["series"], number=v["number"],
        voucher_date=v["voucher_date"], description=v["description"], document_id=v["document_id"],
        reverses_voucher_id=v["reverses_voucher_id"],
        lines=[PostingLine(line_no=r["line_no"], account=r["account_number"], amount_ore=r["amount_ore"],
                           vat_code=r["vat_code"], vat_base_line_no=r["vat_base_line_no"],
                           description=r["description"]) for r in lines],
    )


def trial_balance(conn: Conn, company_id: UUID, date_from: date, date_to: date) -> list[dict]:
    return conn.execute(
        "select l.account_number as account, a.name, sum(l.amount_ore)::bigint as balance_ore"
        " from bokbuzz.voucher_lines l"
        " join bokbuzz.vouchers v on v.id = l.voucher_id"
        " join bokbuzz.accounts a on a.company_id = l.company_id and a.number = l.account_number"
        " where l.company_id = %s and v.voucher_date between %s and %s"
        " group by l.account_number, a.name order by l.account_number",
        [company_id, date_from, date_to],
    ).fetchall()


def close_period(conn: Conn, *, company_id: UUID, actor: UUID, year: int, month: int) -> None:
    require_role(conn, company_id, actor, POSTING_ROLES)
    row = conn.execute(
        "update bokbuzz.periods set status = 'closed', closed_at = now(), closed_by = %s"
        " where company_id = %s and year = %s and month = %s and status = 'open' returning year",
        [actor, company_id, year, month],
    ).fetchone()
    if not row:
        raise Conflict("Perioden finnes ikke eller er allerede lukket", code="period_not_open")
    audit.record(conn, company_id=company_id, actor=actor, event_type="period.closed",
                 entity_type="period", entity_id=f"{year}-{month:02d}")
