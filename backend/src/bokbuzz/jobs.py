"""Jobbkø i Postgres. Jobben legges i kø i samme transaksjon som dataene
(outbox). Arbeideren tar en jobb med lease; krasjer den, tas jobben opp igjen når
leasen går ut. Arbeidet og «ferdig»-markeringen committes i samme transaksjon,
så en jobb gir aldri dobbelt resultat."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from .db import Conn, Database

log = logging.getLogger(__name__)

Handler = Callable[[Conn, dict], None]


def enqueue(
    conn: Conn, *, kind: str, payload: dict[str, Any], company_id: UUID | None = None,
    dedupe_key: str | None = None,
) -> None:
    conn.execute(
        "insert into bokbuzz.jobs (company_id, kind, payload, dedupe_key) values (%s, %s, %s, %s)"
        " on conflict (dedupe_key) do nothing",
        [company_id, kind, Jsonb(payload), dedupe_key],
    )


def claim(conn: Conn, lease_seconds: int, company_id: UUID | None = None) -> dict | None:
    # Jobber som har brukt opp forsøkene og har utløpt lease, markeres som feilet.
    conn.execute(
        "update bokbuzz.jobs set status = 'failed', finished_at = now(),"
        " last_error = coalesce(last_error, 'lease utløpt etter siste forsøk')"
        " where status = 'running' and lease_until < now() and attempts >= max_attempts"
    )
    return conn.execute(
        "update bokbuzz.jobs set status = 'running', attempts = attempts + 1,"
        " lease_until = now() + make_interval(secs => %s)"
        " where id = (select id from bokbuzz.jobs"
        "   where ((status = 'queued' and run_after <= now())"
        "      or (status = 'running' and lease_until < now() and attempts < max_attempts))"
        "     and (%s::uuid is null or company_id = %s)"
        "   order by run_after, id for update skip locked limit 1)"
        " returning *",
        [lease_seconds, company_id, company_id],
    ).fetchone()


def run_once(
    db: Database, handlers: dict[str, Handler], lease_seconds: int = 300, company_id: UUID | None = None
) -> bool:
    """Kjører maks én jobb. Returnerer False når køen er tom."""
    with db.tx() as conn:
        job = claim(conn, lease_seconds, company_id)
    if job is None:
        return False
    handler = handlers.get(job["kind"])
    try:
        with db.tx() as conn:
            if handler is None:
                raise RuntimeError(f"Ingen handler for {job['kind']}")
            handler(conn, job)
            conn.execute("update bokbuzz.jobs set status = 'done', finished_at = now(), lease_until = null"
                         " where id = %s", [job["id"]])
    except Exception:
        err = traceback.format_exc(limit=5)
        log.exception("Jobb %s (%s) feilet", job["id"], job["kind"])
        with db.tx() as conn:
            final = job["attempts"] >= job["max_attempts"]
            conn.execute(
                "update bokbuzz.jobs set status = %s, last_error = %s, lease_until = null,"
                " run_after = now() + make_interval(secs => %s), finished_at = case when %s then now() end"
                " where id = %s",
                ["failed" if final else "queued", err[-4000:], 2 ** min(job["attempts"], 10), final, job["id"]],
            )
    return True
