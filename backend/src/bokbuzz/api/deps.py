"""Felles avhengigheter for API-et."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request

from ..auth import AuthError, Principal, TokenVerifier
from ..config import Settings
from ..db import Database
from ..documents.storage import DocumentStorage
from ..ledger.service import member_role


@dataclass
class Services:
    settings: Settings
    db: Database
    storage: DocumentStorage
    verifier: TokenVerifier


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


def get_principal(
    services: ServicesDep, authorization: Annotated[str | None, Header()] = None
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail={"error": "unauthenticated", "message": "Mangler innlogging"})
    try:
        principal = services.verifier.verify(authorization[7:].strip())
    except AuthError as exc:
        raise HTTPException(401, detail={"error": "unauthenticated", "message": str(exc)}) from exc
    if services.settings.require_mfa and not principal.has_mfa:
        raise HTTPException(403, detail={"error": "mfa_required", "message": "Tofaktorinnlogging kreves"})
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


@dataclass(frozen=True)
class CompanyContext:
    company_id: UUID
    principal: Principal
    role: str

    @property
    def user_id(self) -> UUID:
        return self.principal.user_id


def get_company(company_id: UUID, principal: PrincipalDep, services: ServicesDep) -> CompanyContext:
    """Selskapet må finnes og brukeren må være medlem. Ellers 404, slik at det
    ikke lekker om selskapet finnes."""
    with services.db.tx(principal.user_id) as conn:
        role = member_role(conn, company_id, principal.user_id)
    if role is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "Selskapet finnes ikke"})
    return CompanyContext(company_id=company_id, principal=principal, role=role)


CompanyDep = Annotated[CompanyContext, Depends(get_company)]
