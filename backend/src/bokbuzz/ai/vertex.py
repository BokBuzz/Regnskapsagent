"""Gemini via Vertex AI på EU-endepunktet. Krever `pip install bokbuzz[gcp]`
og at Cloud Run-tjenestekontoen har rollen Vertex AI User. Bruk aldri
AI Studio-nøkler (GEMINI_API_KEY) med kundedata."""

from __future__ import annotations

from .base import ModelRequest, ModelResponse


class VertexGeminiModel:
    def __init__(self, model: str, project: str, location: str = "eu") -> None:
        from google import genai

        self.name = model
        self._client = genai.Client(vertexai=True, project=project, location=location)

    def generate(self, request: ModelRequest) -> ModelResponse:
        from google.genai import types

        resp = self._client.models.generate_content(
            model=self.name,
            contents=[
                types.Part.from_bytes(data=request.content, mime_type=request.mime_type),
                request.prompt,
            ],
            config=types.GenerateContentConfig(
                system_instruction=request.system,
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=request.response_schema,
            ),
        )
        meta = resp.usage_metadata
        usage = {
            "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
        }
        return ModelResponse(text=resp.text or "", model=self.name, usage=usage)
