"""Startpunkt for API-et:  uvicorn bokbuzz.main:app"""

from __future__ import annotations

import logging

from .api.app import create_app
from .api.deps import Services
from .auth import TokenVerifier
from .config import get_settings
from .db import Database
from .wiring import build_storage

logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')

settings = get_settings()
app = create_app(Services(
    settings=settings,
    db=Database(settings.database_url, settings.db_app_role, settings.db_pool_max),
    storage=build_storage(settings),
    verifier=TokenVerifier(settings),
))
