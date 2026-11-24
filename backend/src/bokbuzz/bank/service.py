"""Bankagent v1: import av kontoutskrift, avstemming og forslag.

Flyt:
1. import_statement (API, i brukerens transaksjon): kontroll, lagring, banklinjer inn,
   jobb «bank_reconcile» i kø.
2. reconcile (arbeideren): foreslår koblinger mot hovedboken og lager forslag for
   gebyr og renter. Endrer aldri hovedboken.
3. Brukeren bekrefter eller avviser koblinger, og godkjenner forslag i to klikk som
   alle andre forslag.

Avstemmingen er ren regelkode, slik at den er forutsigbar, gratis og testbar."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from uuid import UUID

from psycopg.types.json import Jsonb

from .. import audit, jobs
from ..db import Conn
from ..documents.storage import DocumentStorage
from ..errors import Conflict, NotFound, ValidationFailed
from ..ledger.models import DraftLine, VoucherDraft, content_hash
from ..ledger.money import format_nok
from ..ledger.service import POSTING_ROLES, expand_lines, require_role, rules_version
from . import rules
from .camt import CamtStatement, parse_camt053

IMPORT_ROLES = POSTING_ROLES
# Et kjøp med kort trekkes gjerne noen dager etter kvitteringsdatoen; en overføring kan
# bokføres i banken litt før bilaget er datert.
DAYS_BEFORE = 14
DAYS_AFTER = 3


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
def _bank_account(conn: Conn, company_id: UUID, stmt: CamtStatement) -> dict:
    row = conn.execute(
        "select * from bokbuzz.bank_accounts where company_id = %s and account_id = %s",
        [company_id, stmt.account_id],
    ).fetchone()
    if row:
        if row["currency"] != stmt.currency:
            raise ValidationFailed("Valutaen på utskriften stemmer ikke med bankkontoen", code="camt_currency")
        return row
    if stmt.currency != "NOK":
        raise ValidationFailed("Bankkontoer i utenlandsk valuta støttes ikke ennå", code="camt_currency")
    return conn.execute(
        "insert into bokbuzz.bank_accounts (company_id, account_id, currency, ledger_account)"
        " values (%s, %s, %s, '1920') returning *",
        [company_id, stmt.account_id, stmt.currency],
    ).fetchone()


def import_statement(
    conn: Conn, storage: DocumentStorage, *, company_id: UUID, actor: UUID, data: bytes,
    filename: str | None, max_bytes: int,
) -> list[dict]:
    """Importerer alle utskrifter i filen. Samme fil to ganger gir ingen nye linjer,
    og poster som finnes fra før (overlappende perioder) hoppes over."""
    require_role(conn, company_id, actor, IMPORT_ROLES)
    if not data:
        raise ValidationFailed("Filen er tom", code="empty_file")
    if len(data) > max_bytes:
        raise ValidationFailed("Filen er for stor", code="file_too_large")
    statements = parse_camt053(data)
    for stmt in statements:
        if any(e.currency != stmt.currency for e in stmt.entries):
            raise ValidationFailed("Poster i annen valuta enn kontoen støttes ikke ennå", code="camt_currency")

    sha = hashlib.sha256(data).hexdigest()
    key = f"{company_id}/bank/{sha}.xml"
    storage.put(key, data, "application/xml")

    results: list[dict] = []
    for idx, stmt in enumerate(statements):
        account = _bank_account(conn, company_id, stmt)
        stmt_sha = sha if idx == 0 else hashlib.sha256(f"{sha}:{idx}".encode()).hexdigest()
        existing = conn.execute(
            "select * from bokbuzz.bank_statements where company_id = %s and sha256 = %s",
            [company_id, stmt_sha],
        ).fetchone()
        if existing:
            results.append({**existing, "duplicate": True})
            continue
        known = {r["fingerprint"] for r in conn.execute(
            "select fingerprint from bokbuzz.bank_transactions where company_id = %s and bank_account_id = %s"
            " and fingerprint = any(%s)",
            [company_id, account["id"], [e.fingerprint for e in stmt.entries]],
        ).fetchall()}
        new_entries = [e for e in stmt.entries if e.fingerprint not in known]
        row = conn.execute(
            "insert into bokbuzz.bank_statements (company_id, bank_account_id, sha256, storage_key,"
            " original_filename, statement_ref, from_date, to_date, opening_balance_ore, closing_balance_ore,"
            " entry_count, new_count, balance_ok, imported_by)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning *",
            [company_id, account["id"], stmt_sha, key, (filename or "")[:200] or None, stmt.statement_ref,
             stmt.from_date, stmt.to_date, stmt.opening_balance_ore, stmt.closing_balance_ore,
             len(stmt.entries), len(new_entries), stmt.balance_ok, actor],
        ).fetchone()
        with conn.cursor() as cur:
            cur.executemany(
                "insert into bokbuzz.bank_transactions (company_id, bank_account_id, statement_id, fingerprint,"
                " booking_date, value_date, amount_ore, currency, counterparty_name, counterparty_account,"
                " reference, end_to_end_id, description, bank_ref, bank_tx_code)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [(company_id, account["id"], row["id"], e.fingerprint, e.booking_date, e.value_date,
                  e.amount_ore, e.currency, e.counterparty_name, e.counterparty_account, e.reference,
                  e.end_to_end_id, e.description, e.bank_ref, e.bank_tx_code) for e in new_entries],
            )
        audit.record(conn, company_id=company_id, actor=actor, event_type="bank.statement_imported",
                     entity_type="bank_statement", entity_id=row["id"],
                     payload={"sha256": stmt_sha, "account_id": stmt.account_id, "entries": len(stmt.entries),
                              "new": len(new_entries), "balance_ok": stmt.balance_ok})
        results.append({**row, "duplicate": False})
    jobs.enqueue(conn, kind="bank_reconcile", company_id=company_id,
                 payload={"reason": "import", "sha256": sha}, dedupe_key=f"bank_reconcile:import:{sha}")
    return results


# ---------------------------------------------------------------------------
# Avstemming (kjøres av arbeideren)
# ---------------------------------------------------------------------------
def _open_transactions(conn: Conn, company_id: UUID) -> list[dict]:
    """Banklinjer uten aktiv kobling og uten forslag som venter på brukeren."""
    return conn.execute(
        "select t.*, a.ledger_account from bokbuzz.bank_transactions t"
        " join bokbuzz.bank_accounts a on a.id = t.bank_account_id"
        " where t.company_id = %s"
        " and not exists (select 1 from bokbuzz.bank_matches m where m.transaction_id = t.id"
        "                 and m.status in ('suggested', 'confirmed'))"
        " and not exists (select 1 from bokbuzz.proposals p where p.bank_transaction_id = t.id"
        "                 and p.status in ('pending', 'needs_manual'))"
        " order by t.booking_date, t.id",
        [company_id],
    ).fetchall()


def _candidates(conn: Conn, company_id: UUID, tx: dict) -> list[dict]:
    """Hovedbokslinjer på bankens konto med samme beløp, i datovinduet, som ikke er koblet,
    ikke reversert og ikke allerede avvist for denne banklinjen."""
    return conn.execute(
        "select l.voucher_id, l.line_no, v.voucher_date, v.series, v.number, v.year, v.description"
        " from bokbuzz.voucher_lines l join bokbuzz.vouchers v on v.id = l.voucher_id"
        " where l.company_id = %s and l.account_number = %s and l.amount_ore = %s"
        " and v.voucher_date between %s and %s"
        " and v.reverses_voucher_id is null"
        " and not exists (select 1 from bokbuzz.vouchers r where r.reverses_voucher_id = v.id)"
        " and not exists (select 1 from bokbuzz.bank_matches m where m.voucher_id = l.voucher_id"
        "                 and m.line_no = l.line_no"
        "                 and (m.status in ('suggested', 'confirmed') or m.transaction_id = %s))"
        " order by v.voucher_date, v.number",
        [company_id, tx["ledger_account"], tx["amount_ore"], tx["booking_date"] - timedelta(days=DAYS_BEFORE),
         tx["booking_date"] + timedelta(days=DAYS_AFTER), tx["id"]],
    ).fetchall()


def _pick(tx: dict, cands: list[dict]) -> tuple[dict, str, str] | None:
    if not cands:
        return None
    amount = format_nok(abs(tx["amount_ore"]))
    if len(cands) == 1:
        c = cands[0]
        return c, "exact_unique", (
            f"Samme beløp ({amount} kr) og eneste bilag i perioden: {c['series']}{c['number']}/{c['year']}"
            f" datert {c['voucher_date']:%d.%m.%Y}, banken bokførte {tx['booking_date']:%d.%m.%Y}.")
    dist = sorted(cands, key=lambda c: abs((c["voucher_date"] - tx["booking_date"]).days))
    first, second = dist[0], dist[1]
    d1 = abs((first["voucher_date"] - tx["booking_date"]).days)
    d2 = abs((second["voucher_date"] - tx["booking_date"]).days)
    if d1 < d2:
        return first, "closest_date", (
            f"Samme beløp ({amount} kr). {len(cands)} bilag passer, og {first['series']}{first['number']}"
            f"/{first['year']} ligger nærmest i dato ({d1} dager). Kontroller at det er riktig bilag.")
    return None  # like nære: vi gjetter ikke


def _rule_proposal(conn: Conn, company_id: UUID, tx: dict, rv: str) -> dict | None:
    rule = rules.classify(tx["amount_ore"], tx["bank_tx_code"], tx["description"])
    if rule is None or (rule.direction == "out") != (tx["amount_ore"] < 0):
        return None
    if conn.execute("select 1 from bokbuzz.proposals where bank_transaction_id = %s limit 1",
                    [tx["id"]]).fetchone():
        return None  # brukeren har allerede godkjent eller avvist et forslag for linjen
    amount = abs(tx["amount_ore"])
    sign = 1 if rule.direction == "out" else -1
    text = (tx["description"] or rule.label)[:200]
    draft = VoucherDraft(
        voucher_date=tx["booking_date"], description=f"{rule.label}: {text}"[:500],
        lines=[DraftLine(account=rule.account, amount_ore=sign * amount, description=rule.label),
               DraftLine(account=tx["ledger_account"], amount_ore=-sign * amount, description="Bank")],
    )
    try:
        expand_lines(conn, company_id, draft)
    except ValidationFailed:
        return None  # kontoen finnes ikke i selskapets kontoplan; brukeren må føre selv
    input_hash = hashlib.sha256(f"{tx['id']}|{rules.RULES_VERSION}|{rv}".encode()).hexdigest()
    explanation = (f"{rule.why} Kontoutskriften fra banken er dokumentasjonen for posten "
                   f"({format_nok(amount)} kr, {tx['booking_date']:%d.%m.%Y}).")
    row = conn.execute(
        "insert into bokbuzz.proposals (company_id, bank_transaction_id, status, model, prompt_version,"
        " rules_version, input_hash, draft, draft_hash, explanation, warnings)"
        " values (%s, %s, 'pending', 'rules', %s, %s, %s, %s, %s, %s, '[]'::jsonb)"
        " on conflict (bank_transaction_id, input_hash) where bank_transaction_id is not null do nothing"
        " returning *",
        [company_id, tx["id"], rules.RULES_VERSION, rv, input_hash, Jsonb(draft.model_dump(mode="json")),
         content_hash(draft), explanation],
    ).fetchone()
    if row:
        audit.record(conn, company_id=company_id, actor=None, event_type="proposal.created",
                     entity_type="proposal", entity_id=row["id"],
                     payload={"bank_transaction_id": str(tx["id"]), "rule": rule.key,
                              "rules_version": rv, "input_hash": input_hash})
    return row


def reconcile(conn: Conn, company_id: UUID) -> dict:
    """Foreslår koblinger og lager regelforslag. Idempotent: kan kjøres så ofte man vil."""
    conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"bank_reconcile:{company_id}"])
    rv = rules_version(conn, company_id)
    matched = proposed = 0
    for tx in _open_transactions(conn, company_id):
        picked = _pick(tx, _candidates(conn, company_id, tx))
        if picked:
            cand, method, why = picked
            row = conn.execute(
                "insert into bokbuzz.bank_matches (company_id, transaction_id, voucher_id, line_no, method,"
                " explanation) values (%s, %s, %s, %s, %s, %s) on conflict do nothing returning id",
                [company_id, tx["id"], cand["voucher_id"], cand["line_no"], method, why],
            ).fetchone()
            if row:
                matched += 1
                audit.record(conn, company_id=company_id, actor=None, event_type="bank.match_suggested",
                             entity_type="bank_match", entity_id=row["id"],
                             payload={"transaction_id": str(tx["id"]), "voucher_id": str(cand["voucher_id"]),
                                      "method": method})
            continue
        if _rule_proposal(conn, company_id, tx, rv):
            proposed += 1
    return {"matches_suggested": matched, "proposals_created": proposed}


def reconcile_job():
    def handler(conn: Conn, job: dict) -> None:
        reconcile(conn, job["company_id"])
    return handler


def request_reconcile(conn: Conn, company_id: UUID, reason: str, key: str) -> None:
    jobs.enqueue(conn, kind="bank_reconcile", company_id=company_id, payload={"reason": reason},
                 dedupe_key=f"bank_reconcile:{reason}:{key}")


# ---------------------------------------------------------------------------
# Brukerens beslutninger
# ---------------------------------------------------------------------------
def decide_match(conn: Conn, *, company_id: UUID, actor: UUID, match_id: UUID, accept: bool) -> dict:
    require_role(conn, company_id, actor, POSTING_ROLES)
    row = conn.execute(
        "select * from bokbuzz.bank_matches where company_id = %s and id = %s for update", [company_id, match_id]
    ).fetchone()
    if not row:
        raise NotFound("Koblingen finnes ikke")
    if row["status"] != "suggested":
        raise Conflict("Koblingen er allerede behandlet", code="match_decided")
    status = "confirmed" if accept else "rejected"
    updated = conn.execute(
        "update bokbuzz.bank_matches set status = %s, decided_by = %s, decided_at = now() where id = %s"
        " returning *", [status, actor, match_id],
    ).fetchone()
    audit.record(conn, company_id=company_id, actor=actor, event_type=f"bank.match_{status}",
                 entity_type="bank_match", entity_id=match_id,
                 payload={"transaction_id": str(row["transaction_id"]), "voucher_id": str(row["voucher_id"])})
    if not accept:
        request_reconcile(conn, company_id, "match_rejected", str(match_id))
    return updated


def link_posted_proposal(conn: Conn, *, company_id: UUID, actor: UUID, proposal: dict, voucher_id: UUID) -> None:
    """Et forslag laget fra en banklinje er avstemt med det samme bilaget det ga."""
    tx_id = proposal.get("bank_transaction_id")
    if not tx_id:
        return
    line = conn.execute(
        "select l.line_no from bokbuzz.voucher_lines l"
        " join bokbuzz.bank_transactions t on t.id = %s"
        " join bokbuzz.bank_accounts a on a.id = t.bank_account_id"
        " where l.voucher_id = %s and l.account_number = a.ledger_account and l.amount_ore = t.amount_ore"
        " order by l.line_no limit 1",
        [tx_id, voucher_id],
    ).fetchone()
    if not line:
        return  # brukeren rettet bankkontoen eller beløpet; da avstemmes linjen på vanlig måte
    row = conn.execute(
        "insert into bokbuzz.bank_matches (company_id, transaction_id, voucher_id, line_no, status, method,"
        " explanation, decided_by, decided_at) values (%s, %s, %s, %s, 'confirmed', 'from_proposal', %s, %s, now())"
        " on conflict do nothing returning id",
        [company_id, tx_id, voucher_id, line["line_no"], "Bilaget ble laget fra denne banklinjen.", actor],
    ).fetchone()
    if row:
        audit.record(conn, company_id=company_id, actor=actor, event_type="bank.match_confirmed",
                     entity_type="bank_match", entity_id=row["id"],
                     payload={"transaction_id": str(tx_id), "voucher_id": str(voucher_id),
                              "method": "from_proposal"})


# ---------------------------------------------------------------------------
# Lesing
# ---------------------------------------------------------------------------
TX_STATUS_SQL = """
  case
    when exists (select 1 from bokbuzz.bank_matches m where m.transaction_id = t.id and m.status = 'confirmed')
      then 'matched'
    when exists (select 1 from bokbuzz.bank_matches m where m.transaction_id = t.id and m.status = 'suggested')
      then 'suggested'
    when exists (select 1 from bokbuzz.proposals p where p.bank_transaction_id = t.id
                   and p.status in ('pending', 'needs_manual'))
      then 'proposed'
    else 'missing_document'
  end
"""


def list_transactions(conn: Conn, company_id: UUID, status: str | None = None,
                      date_from: date | None = None, date_to: date | None = None) -> list[dict]:
    return conn.execute(
        f"select * from (select t.*, {TX_STATUS_SQL} as status,"
        " (select row_to_json(m) from bokbuzz.bank_matches m where m.transaction_id = t.id"
        "   and m.status in ('suggested', 'confirmed')) as match,"
        " (select row_to_json(x) from (select v.series, v.number, v.year, v.voucher_date, v.description"
        "   from bokbuzz.bank_matches m join bokbuzz.vouchers v on v.id = m.voucher_id"
        "   where m.transaction_id = t.id and m.status in ('suggested', 'confirmed')) x) as voucher,"
        " (select p.id from bokbuzz.proposals p where p.bank_transaction_id = t.id"
        "   and p.status in ('pending', 'needs_manual') limit 1) as proposal_id"
        " from bokbuzz.bank_transactions t where t.company_id = %s"
        " and (%s::date is null or t.booking_date >= %s) and (%s::date is null or t.booking_date <= %s)) s"
        " where (%s::text is null or s.status = %s)"
        " order by booking_date desc, created_at desc limit 2000",
        [company_id, date_from, date_from, date_to, date_to, status, status],
    ).fetchall()


def reconciliation_status(conn: Conn, company_id: UUID) -> list[dict]:
    """Per bankkonto: siste saldo fra banken mot saldo i hovedboken på samme dato."""
    accounts = conn.execute(
        "select * from bokbuzz.bank_accounts where company_id = %s order by created_at", [company_id]
    ).fetchall()
    out = []
    for acc in accounts:
        last = conn.execute(
            "select * from bokbuzz.bank_statements where bank_account_id = %s and closing_balance_ore is not null"
            " and to_date is not null order by to_date desc, created_at desc limit 1", [acc["id"]],
        ).fetchone()
        counts = conn.execute(
            f"select s.status, count(*)::int as n from (select {TX_STATUS_SQL} as status"
            " from bokbuzz.bank_transactions t where t.bank_account_id = %s) s group by s.status",
            [acc["id"]],
        ).fetchall()
        ledger = None
        if last:
            ledger = conn.execute(
                "select coalesce(sum(l.amount_ore), 0)::bigint as b from bokbuzz.voucher_lines l"
                " join bokbuzz.vouchers v on v.id = l.voucher_id"
                " where l.company_id = %s and l.account_number = %s and v.voucher_date <= %s",
                [company_id, acc["ledger_account"], last["to_date"]],
            ).fetchone()["b"]
        out.append({
            "bank_account": acc,
            "as_of": last["to_date"] if last else None,
            "bank_balance_ore": last["closing_balance_ore"] if last else None,
            "ledger_balance_ore": ledger,
            "difference_ore": (last["closing_balance_ore"] - ledger) if last else None,
            "counts": {c["status"]: c["n"] for c in counts},
        })
    return out
