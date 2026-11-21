"""Datamodeller for hovedboken."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

AccountNumber = Annotated[str, Field(pattern=r"^[0-9]{4,6}$")]
Series = Annotated[str, Field(pattern=r"^[A-Z]{1,3}$")]


class DraftLine(BaseModel):
    """En bilagslinje slik brukeren godkjenner den. amount_ore er nettobeløp i NOK
    (debet positivt, kredit negativt). Har linjen en MVA-kode med sats, legger
    hovedboken selv til MVA-linjen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account: AccountNumber
    amount_ore: int
    vat_code: str | None = None
    vat_amount_ore: int | None = None
    description: str | None = Field(default=None, max_length=300)

    @field_validator("amount_ore")
    @classmethod
    def _nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("Beløpet kan ikke være 0")
        if abs(v) > 10**13:
            raise ValueError("Beløpet er urimelig stort")
        return v


class VoucherDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    voucher_date: date
    description: str = Field(min_length=1, max_length=500)
    lines: list[DraftLine] = Field(min_length=1, max_length=200)


class ReversalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reverses_voucher_id: UUID
    reason: str = Field(min_length=3, max_length=500)
    voucher_date: date


class PostingLine(BaseModel):
    """En ferdig linje slik den lagres i hovedboken."""

    model_config = ConfigDict(frozen=True)

    line_no: int
    account: str
    amount_ore: int
    vat_code: str | None = None
    vat_base_line_no: int | None = None
    description: str | None = None


class PostedVoucher(BaseModel):
    id: UUID
    company_id: UUID
    year: int
    series: str
    number: int
    voucher_date: date
    description: str
    document_id: UUID | None
    reverses_voucher_id: UUID | None
    lines: list[PostingLine]
    created: bool = True  # False når idempotensnøkkelen ga et eksisterende bilag


def content_hash(obj: BaseModel) -> str:
    """Stabil hash av innholdet brukeren godkjente."""
    data = obj.model_dump(mode="json")
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()
