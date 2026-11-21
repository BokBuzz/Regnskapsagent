"""Lagring av originalbilag. Nøkkelen er innholdsadressert (SHA-256), og en
eksisterende fil blir aldri overskrevet. I produksjon brukes Cloud Storage med
Bucket Lock (WORM), som eier setter opp (se docs/OPPSETT.md)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class DocumentStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...


class LocalStorage:
    """For utvikling og tester. Ikke for ekte bilag."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Ugyldig lagringsnøkkel")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        if path.exists():
            return  # innholdsadressert: samme nøkkel = samme innhold
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class GCSStorage:
    """Google Cloud Storage. Bøtta skal ha versjonering og låst oppbevaringsregel."""

    def __init__(self, bucket: str) -> None:
        from google.cloud import storage  # valgfri avhengighet: pip install bokbuzz[gcp]

        self.bucket = storage.Client().bucket(bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        from google.api_core.exceptions import PreconditionFailed

        blob = self.bucket.blob(key)
        try:
            blob.upload_from_string(data, content_type=content_type, if_generation_match=0)
        except PreconditionFailed:
            pass  # finnes allerede med samme innhold

    def get(self, key: str) -> bytes:
        return self.bucket.blob(key).download_as_bytes()
