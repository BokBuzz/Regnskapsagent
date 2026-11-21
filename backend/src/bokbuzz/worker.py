"""Jobbarbeider:  python -m bokbuzz.worker"""

from __future__ import annotations

import logging
import signal
import time

from . import jobs
from .config import get_settings
from .db import Database
from .proposals.service import extract_document_job
from .wiring import build_router, build_storage

log = logging.getLogger("bokbuzz.worker")


def main() -> None:
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
    log.info("Arbeider startet")
    while not stopping:
        if not jobs.run_once(db, handlers, settings.job_lease_seconds):
            time.sleep(2)
    db.close()


if __name__ == "__main__":
    main()
