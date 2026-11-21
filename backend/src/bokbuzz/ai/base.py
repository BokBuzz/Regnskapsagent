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
class ModelPrice:
    """Pris i USD per million tokens."""

    input_per_m: float
    output_per_m: float

    def micro_usd(self, usage: dict[str, int]) -> int:
        # 1 USD per 1M tokens = 1 mikro-USD per token.
        return round(usage.get("input_tokens", 0) * self.input_per_m
                     + usage.get("output_tokens", 0) * self.output_per_m)


@dataclass(frozen=True)
class ModelRouter:
    """Billig modell først, sterkere modell ved tvetydighet, og et kostnadstak per selskap og måned."""

    default: SuggestionModel
    escalation: SuggestionModel
    prices: dict[str, ModelPrice] = field(default_factory=dict)
    monthly_cap_micro_usd: int | None = None

    def cost(self, model: str, usage: dict[str, int]) -> int:
        price = self.prices.get(model)
        return price.micro_usd(usage) if price else 0
