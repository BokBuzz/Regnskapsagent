"""Det strukturerte svaret modellen må gi. Beløp i heltall øre."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtractedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(max_length=300)
    net_amount_ore: int
    vat_amount_ore: int
    account: str = Field(pattern=r"^[0-9]{4,6}$")
    vat_code: str


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_kind: Literal["receipt", "invoice", "credit_note", "settlement", "other"]
    supplier_name: str | None = Field(default=None, max_length=200)
    supplier_orgnr: str | None = None
    document_date: date | None = None
    currency: str = Field(default="NOK", pattern=r"^[A-Z]{3}$")
    total_amount_ore: int
    payment: Literal["bank", "private", "cash", "unpaid", "unknown"]
    lines: list[ExtractedLine] = Field(min_length=1, max_length=50)
    ambiguous: bool = False
    ambiguity_reasons: list[str] = Field(default_factory=list, max_length=10)


def response_schema() -> dict:
    return Extraction.model_json_schema()
