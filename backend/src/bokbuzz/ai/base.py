"""Leverandørnøytralt grensesnitt mot språkmodeller.

Modellen har ingen verktøy og ingen skrivetilgang. Den får dokumentet og en
instruks, og returnerer tekst (JSON) som valideres strengt etterpå."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelRequest:
    system: str
    prompt: str
    content: bytes
    mime_type: str
    response_schema: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


class SuggestionModel(Protocol):
    name: str

    def generate(self, request: ModelRequest) -> ModelResponse: ...


@dataclass(frozen=True)
class ModelRouter:
    """Billig modell først, sterkere modell ved tvetydighet."""

    default: SuggestionModel
    escalation: SuggestionModel
