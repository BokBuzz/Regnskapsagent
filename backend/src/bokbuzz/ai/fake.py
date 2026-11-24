"""Falsk modell for tester og lokal utvikling. Sender aldri data ut."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .base import ModelRequest, ModelResponse

DEMO_RESPONSE: dict[str, Any] = {
    "document_kind": "receipt",
    "supplier_name": "Demo Bensinstasjon AS",
    "supplier_orgnr": "923609016",
    "document_date": None,  # settes til dagens dato ved kall
    "currency": "NOK",
    "total_amount_ore": 62500,
    "payment": "bank",
    "lines": [
        {"description": "Diesel", "net_amount_ore": 50000, "vat_amount_ore": 12500,
         "account": "7000", "vat_code": "1"},
    ],
    "ambiguous": False,
    "ambiguity_reasons": [],
    "explanation": "Diesel til firmabilen er en bilkostnad, og du har fradrag for 25 % MVA.",
}


def _demo(_: ModelRequest) -> dict[str, Any]:
    from ..ledger.money import oslo_today

    return {**DEMO_RESPONSE, "document_date": oslo_today().isoformat()}


class FakeModel:
    def __init__(
        self,
        name: str = "fake-model",
        response: dict[str, Any] | str | Callable[[ModelRequest], dict[str, Any] | str] | None = None,
    ) -> None:
        self.name = name
        self.response = _demo if response is None else response
        self.calls: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        value = self.response(request) if callable(self.response) else self.response
        text = value if isinstance(value, str) else json.dumps(value)
        return ModelResponse(text=text, model=self.name, usage={"input_tokens": 0, "output_tokens": 0})
