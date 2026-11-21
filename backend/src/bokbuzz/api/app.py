"""FastAPI-applikasjonen."""

from __future__ import annotations

import logging
import uuid

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..errors import DomainError
from .deps import Services
from .routes import router

log = logging.getLogger("bokbuzz.api")


def create_app(services: Services) -> FastAPI:
    app = FastAPI(title="Bokbuzz API", version="0.1.0",
                  docs_url="/docs" if services.settings.environment != "prod" else None,
                  redoc_url=None)
    app.state.services = services
    app.include_router(router)

    @app.middleware("http")
    async def correlation_id(request: Request, call_next):
        cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        request.state.correlation_id = cid
        response = await call_next(request)
        response.headers["x-correlation-id"] = cid
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["cache-control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status_code)

    @app.exception_handler(psycopg.errors.RaiseException)
    async def db_guard(_: Request, exc: psycopg.errors.RaiseException) -> JSONResponse:
        hint = exc.diag.message_hint or "db_guard"
        return JSONResponse({"error": hint, "message": exc.diag.message_primary}, status_code=409)

    @app.exception_handler(psycopg.errors.UniqueViolation)
    async def unique(_: Request, exc: psycopg.errors.UniqueViolation) -> JSONResponse:
        return JSONResponse({"error": "conflict", "message": "Finnes allerede"}, status_code=409)

    @app.exception_handler(psycopg.errors.CheckViolation)
    async def check(_: Request, exc: psycopg.errors.CheckViolation) -> JSONResponse:
        return JSONResponse({"error": "invalid", "message": exc.diag.message_primary}, status_code=422)

    return app
