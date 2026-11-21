"""Revisjonslogg. Hash-kjeden beregnes av databasen (trigger), slik at ingen
kodevei kan skrive en hendelse utenom kjeden."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from .db import Conn


def record(
    conn: Conn,
    *,
    company_id: UUID,
    actor: UUID | None,
    event_type: str,
    entity_type: str | None = None,
    entity_id: Any = None,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "insert into bokbuzz.audit_events (company_id, actor, event_type, entity_type, entity_id, payload)"
        " values (%s, %s, %s, %s, %s, %s)",
        [company_id, actor, event_type, entity_type,
         None if entity_id is None else str(entity_id), Jsonb(payload or {})],
    )


def verify_chain(conn: Conn, company_id: UUID) -> int | None:
    """Returnerer første sekvensnummer der kjeden er brutt, ellers None."""
    row = conn.execute("select bokbuzz.verify_audit_chain(%s) as bad", [company_id]).fetchone()
    return row["bad"]
