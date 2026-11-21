"""Verifisering av Supabase Auth-tokens (JWT). Autorisering per selskap skjer
i API-et og i databasen (RLS)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from uuid import UUID

import jwt

from .config import Settings


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    aal: str
    email: str | None = None

    @property
    def has_mfa(self) -> bool:
        return self.aal == "aal2"


class AuthError(Exception):
    pass


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @cached_property
    def _jwks(self) -> jwt.PyJWKClient:
        if not self.settings.supabase_url:
            raise AuthError("Innlogging er ikke konfigurert")
        return jwt.PyJWKClient(f"{self.settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
                               cache_keys=True)

    def verify(self, token: str) -> Principal:
        try:
            if self.settings.supabase_jwt_secret is not None:
                claims = jwt.decode(token, self.settings.supabase_jwt_secret.get_secret_value(),
                                    algorithms=["HS256"], audience=self.settings.jwt_audience)
            else:
                key = self._jwks.get_signing_key_from_jwt(token)
                claims = jwt.decode(token, key.key, algorithms=["RS256", "ES256"],
                                    audience=self.settings.jwt_audience)
            return Principal(user_id=UUID(claims["sub"]), aal=claims.get("aal", "aal1"),
                             email=claims.get("email"))
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise AuthError("Ugyldig innlogging") from exc
