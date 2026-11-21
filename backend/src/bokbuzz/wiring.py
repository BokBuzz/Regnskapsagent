"""Bygger tjenestene fra konfigurasjon."""

from __future__ import annotations

from .ai.base import ModelRouter
from .ai.fake import FakeModel
from .config import Settings
from .documents.storage import DocumentStorage, GCSStorage, LocalStorage


def build_storage(settings: Settings) -> DocumentStorage:
    if settings.storage_backend == "gcs":
        if not settings.gcs_bucket:
            raise RuntimeError("BOKBUZZ_GCS_BUCKET må settes")
        return GCSStorage(settings.gcs_bucket)
    if settings.environment == "prod":
        raise RuntimeError("Lokal lagring er ikke tillatt i produksjon")
    return LocalStorage(settings.local_storage_dir)


def build_router(settings: Settings) -> ModelRouter:
    if settings.ai_provider == "vertex":
        from .ai.vertex import VertexGeminiModel

        if not settings.gcp_project:
            raise RuntimeError("BOKBUZZ_GCP_PROJECT må settes")
        return ModelRouter(
            default=VertexGeminiModel(settings.model_default, settings.gcp_project, settings.vertex_location),
            escalation=VertexGeminiModel(settings.model_escalation, settings.gcp_project,
                                         settings.vertex_location),
        )
    if settings.environment == "prod":
        raise RuntimeError("Falsk modell er ikke tillatt i produksjon")
    return ModelRouter(default=FakeModel("fake-default"), escalation=FakeModel("fake-escalation"))
