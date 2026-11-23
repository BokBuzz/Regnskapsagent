"""Oppslag i Enhetsregisteret (Brønnøysundregistrene). Åpne data, ingen nøkkel."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .errors import DomainError, NotFound


@dataclass(frozen=True)
class Entity:
    orgnr: str
    name: str
    org_form: str
    vat_registered: bool
    deleted: bool
    address: str | None


class LookupUnavailable(DomainError):
    status_code = 503
    code = "lookup_unavailable"


def lookup(orgnr: str, base_url: str, client: httpx.Client | None = None) -> Entity:
    own = client is None
    client = client or httpx.Client(timeout=5)
    try:
        resp = client.get(f"{base_url.rstrip('/')}/{orgnr}", headers={"accept": "application/json"})
    except httpx.HTTPError as exc:
        raise LookupUnavailable("Brønnøysundregistrene svarer ikke nå; prøv igjen senere") from exc
    finally:
        if own:
            client.close()
    if resp.status_code in (404, 410):
        raise NotFound("Fant ikke organisasjonsnummeret i Enhetsregisteret")
    if resp.status_code != 200:
        raise LookupUnavailable("Brønnøysundregistrene svarer ikke nå; prøv igjen senere")
    data = resp.json()
    addr = data.get("forretningsadresse") or data.get("postadresse") or {}
    address = ", ".join(p for p in [" ".join(addr.get("adresse") or []), addr.get("postnummer"),
                                    addr.get("poststed")] if p) or None
    return Entity(
        orgnr=data.get("organisasjonsnummer", orgnr),
        name=data.get("navn", ""),
        org_form=(data.get("organisasjonsform") or {}).get("kode", ""),
        vat_registered=bool(data.get("registrertIMvaregisteret")),
        deleted=bool(data.get("slettedato")),
        address=address,
    )
