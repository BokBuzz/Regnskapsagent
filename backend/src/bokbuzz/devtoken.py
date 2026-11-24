"""Lager et innloggingstoken for lokal utvikling (aldri i produksjon):

    BOKBUZZ_SUPABASE_JWT_SECRET=... python -m bokbuzz.devtoken [bruker-uuid]
"""

from __future__ import annotations

import sys
import time
import uuid

import jwt

from .config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.environment == "prod" or settings.supabase_jwt_secret is None:
        sys.exit("Bare for lokal utvikling med BOKBUZZ_SUPABASE_JWT_SECRET satt")
    user = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
    now = int(time.time())
    claims = {"sub": user, "aud": settings.jwt_audience, "aal": "aal2", "role": "authenticated",
              "email": "utvikler@example.com", "iat": now, "exp": now + 8 * 3600}
    print(jwt.encode(claims, settings.supabase_jwt_secret.get_secret_value(), algorithm="HS256"))


if __name__ == "__main__":
    main()
