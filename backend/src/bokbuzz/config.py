"""Konfigurasjon fra miljøvariabler (prefiks BOKBUZZ_)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOKBUZZ_", env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "prod"] = "dev"

    # Database. Innloggingsbrukeren i URL-en må være medlem av rollene under.
    database_url: str = "postgresql://postgres:postgres@localhost:5432/bokbuzz"
    db_app_role: str = "bokbuzz_app"
    db_worker_role: str = "bokbuzz_worker"
    db_pool_max: int = 10

    # Supabase Auth. Enten JWKS (anbefalt, asymmetriske nøkler) eller delt hemmelighet.
    supabase_url: str | None = None
    supabase_jwt_secret: SecretStr | None = None
    jwt_audience: str = "authenticated"
    require_mfa: bool = True

    # Nettlesere som får kalle API-et (appens adresse). Tom liste = ingen.
    cors_origins: list[str] = ["http://localhost:5173"]
    brreg_url: str = "https://data.brreg.no/enhetsregisteret/api/enheter"

    # Lagring av originalbilag
    storage_backend: Literal["local", "gcs"] = "local"
    local_storage_dir: str = "./var/documents"
    gcs_bucket: str | None = None
    max_upload_bytes: int = 15 * 1024 * 1024

    # KI. Modellnavn ligger i konfigurasjon, slik at bytte ikke krever kodeendring.
    # VERIFISER eksakte modell-ID-er i Vertex AI før produksjon.
    ai_provider: Literal["fake", "vertex"] = "fake"
    gcp_project: str | None = None
    vertex_location: str = "eu"
    model_default: str = "gemini-3.1-flash-lite"
    model_escalation: str = "gemini-3.8-flash"
    vertex_timeout_seconds: int = 90
    # Priser i USD per million tokens (inn, ut) på EU-endepunktet, fra designdokumentet 21.11.2026.
    # Oppdater når Google endrer prisene; brukes bare til kostnadstaket.
    model_prices: dict[str, tuple[float, float]] = {
        "gemini-3.1-flash-lite": (0.275, 1.65),
        "gemini-3.8-flash": (0.825, 4.125),
    }
    # Kostnadstak for KI per selskap og måned. Når taket er nådd, konteres bilag manuelt.
    ai_monthly_cap_usd: float | None = 5.0

    # Godkjenning (to klikk) og jobbkø
    review_token_ttl_seconds: int = 30 * 60
    job_lease_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
