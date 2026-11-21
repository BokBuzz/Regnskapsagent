"""Mottak av bilag: kontroll, hash, uforanderlig lagring og jobb i kø."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from .. import audit, jobs
from ..db import Conn
from ..errors import NotFound, ValidationFailed
from ..ledger.service import require_role
from .filetypes import ALLOWED, sniff_mime
from .storage import DocumentStorage

UPLOAD_ROLES = frozenset({"owner", "accountant"})


@dataclass(frozen=True)
class UploadResult:
    document: dict
    created: bool


def upload_document(
    conn: Conn,
    storage: DocumentStorage,
    *,
    company_id: UUID,
    actor: UUID,
    data: bytes,
    filename: str | None,
    max_bytes: int,
) -> UploadResult:
    require_role(conn, company_id, actor, UPLOAD_ROLES)
    if not data:
        raise ValidationFailed("Filen er tom", code="empty_file")
    if len(data) > max_bytes:
        raise ValidationFailed(f"Filen er større enn {max_bytes // (1024 * 1024)} MB", code="file_too_large")
    mime = sniff_mime(data)
    if mime not in ALLOWED:
        raise ValidationFailed("Filtypen støttes ikke (JPEG, PNG, WEBP, HEIC eller PDF)",
                               code="unsupported_type")
    # TODO(fase 1): virusskanning og isolert parsing før filen sendes videre.

    sha = hashlib.sha256(data).hexdigest()
    existing = _find_by_hash(conn, company_id, sha)
    if existing:
        return UploadResult(existing, created=False)

    key = f"companies/{company_id}/documents/{sha}.{ALLOWED[mime]}"
    storage.put(key, data, mime)
    row = conn.execute(
        "insert into bokbuzz.documents (company_id, sha256, original_filename, mime_type, size_bytes,"
        " storage_key, uploaded_by) values (%s, %s, %s, %s, %s, %s, %s)"
        " on conflict (company_id, sha256) do nothing returning *",
        [company_id, sha, (filename or "")[:255] or None, mime, len(data), key, actor],
    ).fetchone()
    if row is None:  # samtidig opplasting av samme fil
        return UploadResult(_find_by_hash(conn, company_id, sha), created=False)
    jobs.enqueue(conn, kind="extract_document", company_id=company_id,
                 payload={"document_id": str(row["id"])}, dedupe_key=f"extract:{row['id']}")
    audit.record(conn, company_id=company_id, actor=actor, event_type="document.received",
                 entity_type="document", entity_id=row["id"],
                 payload={"sha256": sha, "mime_type": mime, "size_bytes": len(data)})
    return UploadResult(row, created=True)


def _find_by_hash(conn: Conn, company_id: UUID, sha: str) -> dict | None:
    return conn.execute(
        "select * from bokbuzz.documents where company_id = %s and sha256 = %s", [company_id, sha]
    ).fetchone()


def get_document(conn: Conn, company_id: UUID, document_id: UUID) -> dict:
    row = conn.execute(
        "select * from bokbuzz.documents where company_id = %s and id = %s", [company_id, document_id]
    ).fetchone()
    if not row:
        raise NotFound("Dokumentet finnes ikke")
    return row


def read_content(conn: Conn, storage: DocumentStorage, company_id: UUID, document_id: UUID) -> tuple[bytes, str]:
    doc = get_document(conn, company_id, document_id)
    data = storage.get(doc["storage_key"])
    if hashlib.sha256(data).hexdigest() != doc["sha256"]:
        raise RuntimeError(f"Integritetsfeil: dokument {document_id} stemmer ikke med lagret hash")
    return data, doc["mime_type"]
