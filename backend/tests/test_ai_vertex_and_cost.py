"""Vertex-adapteren (uten nettverk), kostnadstak og konfigurasjonsvern."""

from __future__ import annotations

import types as pytypes

import pytest
from test_proposals import proposals, receipt, run_jobs, upload

from bokbuzz.ai.base import ModelPrice, ModelRequest, ModelRouter
from bokbuzz.ai.fake import FakeModel
from bokbuzz.config import Settings
from bokbuzz.proposals.schema import response_schema
from bokbuzz.wiring import build_router, build_storage


class CountingFake(FakeModel):
    def generate(self, request):
        resp = super().generate(request)
        return type(resp)(text=resp.text, model=resp.model, usage={"input_tokens": 4000, "output_tokens": 800})


def test_price_calculation():
    # 4000 inn * 0,275 + 800 ut * 1,65 = 1100 + 1320 mikro-USD
    assert ModelPrice(0.275, 1.65).micro_usd({"input_tokens": 4000, "output_tokens": 800}) == 2420


def test_cost_is_recorded_per_model(client, app_db, worker_db, storage, company, user):
    upload(client, company, user)
    router = ModelRouter(CountingFake("lite", receipt()), CountingFake("strong", receipt()),
                         prices={"lite": ModelPrice(0.275, 1.65)}, monthly_cap_micro_usd=10_000)
    run_jobs(worker_db, storage, router, company)
    [p] = proposals(app_db, user, company)
    assert p["usage"]["lite"]["cost_micro_usd"] == 2420


def test_cost_cap_stops_model_calls(client, app_db, worker_db, storage, company, user):
    router = ModelRouter(CountingFake("lite", receipt()), CountingFake("strong", receipt()),
                         prices={"lite": ModelPrice(0.275, 1.65)}, monthly_cap_micro_usd=3000)
    upload(client, company, user, seed="en")
    run_jobs(worker_db, storage, router, company)  # 2420 brukt, under taket
    upload(client, company, user, seed="to")
    run_jobs(worker_db, storage, router, company)  # 4840 brukt, over taket
    upload(client, company, user, seed="tre")
    run_jobs(worker_db, storage, router, company)  # stoppes før kall
    ps = proposals(app_db, user, company)
    assert [p["status"] for p in ps] == ["pending", "pending", "needs_manual"]
    assert ps[2]["validation_errors"][0]["code"] == "cost_cap"
    assert len(router.default.calls) == 2


def test_cap_blocks_escalation_but_keeps_record(client, app_db, worker_db, storage, company, user):
    upload(client, company, user)
    router = ModelRouter(CountingFake("lite", receipt(ambiguous=True)), CountingFake("strong", receipt()),
                         prices={"lite": ModelPrice(0.275, 1.65)}, monthly_cap_micro_usd=1000)
    run_jobs(worker_db, storage, router, company)
    [p] = proposals(app_db, user, company)
    assert p["escalated"] is False and len(router.escalation.calls) == 0
    assert "cost_cap" in {w["code"] for w in p["warnings"]}


def test_vertex_adapter_builds_eu_request_without_api_key(monkeypatch):
    captured = {}

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            captured.update(model=model, contents=contents, config=config)
            usage = pytypes.SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=2)
            return pytypes.SimpleNamespace(text='{"ok": true}', usage_metadata=usage)

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.models = FakeModels()

    from google import genai
    monkeypatch.setattr(genai, "Client", FakeClient)
    from bokbuzz.ai.vertex import VertexGeminiModel

    m = VertexGeminiModel("gemini-x", project="p", location="eu", timeout_seconds=30)
    resp = m.generate(ModelRequest(system="s", prompt="p", content=b"%PDF-", mime_type="application/pdf",
                                   response_schema=response_schema()))
    assert captured["client"]["vertexai"] is True and captured["client"]["location"] == "eu"
    assert "api_key" not in captured["client"]
    assert captured["client"]["http_options"].timeout == 30_000
    cfg = captured["config"]
    assert cfg.temperature == 0 and cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema["title"] == "Extraction"
    assert resp.usage == {"input_tokens": 10, "output_tokens": 7}


def test_prod_refuses_fake_model_and_local_storage(tmp_path):
    prod = Settings(environment="prod", ai_provider="fake", storage_backend="local",
                    local_storage_dir=str(tmp_path))
    with pytest.raises(RuntimeError):
        build_router(prod)
    with pytest.raises(RuntimeError):
        build_storage(prod)


def test_vertex_requires_prices_for_configured_models():
    s = Settings(ai_provider="vertex", gcp_project="p", model_default="ukjent-modell")
    with pytest.raises(RuntimeError, match="pris"):
        build_router(s)


def test_worker_health_endpoint(monkeypatch):
    import socket
    import urllib.request

    from bokbuzz import worker
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("PORT", str(port))
    worker._start_health_server()
    assert urllib.request.urlopen(f"http://127.0.0.1:{port}/").status == 200  # noqa: S310
