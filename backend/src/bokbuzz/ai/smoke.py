"""Røyktest av KI-oppsettet etter at Google Cloud er satt opp:

    BOKBUZZ_AI_PROVIDER=vertex BOKBUZZ_GCP_PROJECT=<prosjekt> python -m bokbuzz.ai.smoke

Sender en oppdiktet kvittering (ingen kundedata) til standard- og eskaleringsmodellen
på EU-endepunktet, og viser svaret, valideringen, tokenbruk og kostnad. Bekrefter at
modell-ID-ene finnes og at tjenestekontoen har tilgang."""

from __future__ import annotations

import json
import sys
from datetime import date

from ..config import get_settings
from ..proposals.prompt import SYSTEM, build_prompt
from ..proposals.schema import Extraction, response_schema
from ..proposals.validation import validate
from ..wiring import build_router
from .base import ModelRequest

SYNTHETIC_RECEIPT = """KVITTERING
Testbensin AS  Org.nr 923609016 MVA
Dato: 15.03.2026  Kl 14:02
Diesel 32,10 l                 625,00
Herav MVA 25 %                 125,00
SUM NOK                        625,00
Betalt med kort (bank)
"""

ACCOUNTS = [
    {"number": "7000", "name": "Drivstoff og lading", "account_type": "expense", "default_vat_code": "1"},
    {"number": "7090", "name": "Annen kostnad bil", "account_type": "expense", "default_vat_code": "1"},
    {"number": "7790", "name": "Annen driftskostnad", "account_type": "expense", "default_vat_code": "1"},
]
VAT = [{"code": "1", "rate_bp": 2500, "description": "Fradrag for inngående MVA, alminnelig sats"},
       {"code": "0", "rate_bp": 0, "description": "Ingen MVA-behandling"}]


def main() -> int:
    settings = get_settings()
    router = build_router(settings)
    request = ModelRequest(system=SYSTEM, prompt=build_prompt(ACCOUNTS, VAT),
                           content=SYNTHETIC_RECEIPT.encode(), mime_type="text/plain",
                           response_schema=response_schema())
    ok = True
    for model in (router.default, router.escalation):
        print(f"== {model.name} ({settings.ai_provider}, {settings.vertex_location})")
        try:
            resp = model.generate(request)
            ex = Extraction.model_validate_json(resp.text)
        except Exception as exc:  # noqa: BLE001 - vi vil vise alt som går galt
            print(f"FEIL: {type(exc).__name__}: {exc}")
            ok = False
            continue
        errors, warnings = validate(ex, accounts={a["number"]: a for a in ACCOUNTS},
                                    vat_rates={v["code"]: (v["rate_bp"], "input" if v["code"] == "1" else "none")
                                               for v in VAT}, today=date(2026, 3, 16))
        print(json.dumps(json.loads(ex.model_dump_json()), ensure_ascii=False, indent=2))
        print(f"Tokens: {resp.usage}  Kostnad: {router.cost(model.name, resp.usage) / 1e6:.6f} USD")
        print("Feil:", [e.code for e in errors] or "ingen", " Advarsler:", [w.code for w in warnings] or "ingen")
        ok = ok and not errors
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
