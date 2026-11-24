"""Innsending av MVA-meldingen til Skatteetaten.

Skatteetaten oppgir at MVA-meldingen i 2026 sendes med innlogging i ID-porten: kunden
logger inn, Bokbuzz får et token på kundens vegne, validerer meldingen og sender den
via Altinn. Bokbuzz sender aldri uten at kunden selv har bekreftet i appen.

Denne modulen er klar for å kobles på når Bokbuzz har:
1. ID-porten-integrasjon i Samarbeidsportalen hos Digdir (først testmiljø),
2. tilgang til Skatteetatens scopes for validering og innsending av MVA-meldingen,
3. testdata i Tenor.

Til da gir NotConfigured en tydelig feilmelding, og resten av flyten (beregning,
kontroller og XML) kan testes og brukes som utkast. Se docs/MVA_MELDING.md."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..errors import DomainError


class SubmissionUnavailable(DomainError):
    status_code = 503
    code = "vat_submission_unavailable"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    messages: list[str]


@dataclass(frozen=True)
class SubmissionReceipt:
    reference: str
    status: str


class VatSubmissionClient(Protocol):
    def validate(self, xml: str, *, user_token: str) -> ValidationResult: ...
    def submit(self, xml: str, *, orgnr: str, user_token: str) -> SubmissionReceipt: ...


class NotConfigured:
    """Brukes til Bokbuzz har fått tilgang fra Digdir og Skatteetaten."""

    MESSAGE = ("Innsending til Skatteetaten er ikke koblet til ennå. Bokbuzz venter på tilgang fra Digdir og "
               "Skatteetaten. Last ned utkastet og send det i Altinn til da.")

    def validate(self, xml: str, *, user_token: str) -> ValidationResult:
        raise SubmissionUnavailable(self.MESSAGE)

    def submit(self, xml: str, *, orgnr: str, user_token: str) -> SubmissionReceipt:
        raise SubmissionUnavailable(self.MESSAGE)
