"""Gemini via Vertex AI på EU-endepunktet. Krever `pip install bokbuzz[gcp]`
og at tjenestekontoen har rollen Vertex AI User. Autentisering skjer med
tjenestekontoen (Application Default Credentials), aldri med API-nøkkel.
Bruk aldri AI Studio-nøkler (GEMINI_API_KEY) med kundedata."""

from __future__ import annotations

from .base import ModelRequest, ModelResponse

RETRY_STATUS = [408, 429, 500, 502, 503, 504]


class VertexGeminiModel:
    def __init__(self, model: str, project: str, location: str = "eu", timeout_seconds: int = 90) -> None:
        from google import genai
        from google.genai import types

        self.name = model
        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=types.HttpOptions(
                timeout=timeout_seconds * 1000,
                retry_options=types.HttpRetryOptions(attempts=3, initial_delay=1.0, max_delay=20.0,
                                                     http_status_codes=RETRY_STATUS),
            ),
        )

    def build_config(self, request: ModelRequest):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=request.system,
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=request.response_schema,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        from google.genai import types

        resp = self._client.models.generate_content(
            model=self.name,
            contents=[
                types.Part.from_bytes(data=request.content, mime_type=request.mime_type),
                request.prompt,
            ],
            config=self.build_config(request),
        )
        meta = resp.usage_metadata
        usage = {
            "input_tokens": (getattr(meta, "prompt_token_count", 0) or 0),
            # Tenke-tokens faktureres som output.
            "output_tokens": (getattr(meta, "candidates_token_count", 0) or 0)
            + (getattr(meta, "thoughts_token_count", 0) or 0),
        }
        return ModelResponse(text=resp.text or "", model=self.name, usage=usage)
