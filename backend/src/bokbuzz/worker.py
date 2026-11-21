"""Jobbarbeider:  python -m bokbuzz.worker"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import jobs
from .config import get_settings
from .db import Database
from .proposals.service import extract_document_job
from .wiring import build_router, build_storage

log = logging.getLogger("bokbuzz.worker")


_last_tick = time.monotonic()
STALE_AFTER_SECONDS = 600


class _Health(BaseHTTPRequestHandler):
    """Cloud Run krever at containeren svarer på PORT. Svarer 503 hvis løkken har stått stille."""

    def do_GET(self) -> None:  # noqa: N802
        ok = time.monotonic() - _last_tick < STALE_AFTER_SECONDS
        self.send_response(200 if ok else 503)
        self.end_headers()
        self.wfile.write(b"ok" if ok else b"stale")

    def log_message(self, *args) -> None:
        pass


def _start_health_server() -> None:
    port = os.environ.get("PORT")
    if port:
        server = ThreadingHTTPServer(("0.0.0.0", int(port)), _Health)  # noqa: S104
        threading.Thread(target=server.serve_forever, daemon=True).start()


def main() -> None:
    global _last_tick
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    db = Database(settings.database_url, settings.db_worker_role, max_size=2)
    handlers = {"extract_document": extract_document_job(build_storage(settings), build_router(settings))}
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    _start_health_server()
    log.info("Arbeider startet")
    while not stopping:
        _last_tick = time.monotonic()
        if not jobs.run_once(db, handlers, settings.job_lease_seconds):
            time.sleep(2)
    db.close()


if __name__ == "__main__":
    main()
