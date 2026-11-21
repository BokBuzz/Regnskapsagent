"""Enkel migrasjonskjører: kjører SQL-filene i backend/migrations i rekkefølge,
hver i sin egen transaksjon, og registrerer dem i bokbuzz_meta.schema_migrations.

Bruk:  python -m bokbuzz.migrate  (bruker BOKBUZZ_MIGRATION_DATABASE_URL eller
BOKBUZZ_DATABASE_URL; må være en eierrolle, f.eks. postgres i Supabase)."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(os.environ.get("BOKBUZZ_MIGRATIONS_DIR")
                      or Path(__file__).resolve().parents[2] / "migrations")


def migrate(url: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(url, autocommit=False) as conn:
        conn.execute("create schema if not exists bokbuzz_meta")
        conn.execute(
            "create table if not exists bokbuzz_meta.schema_migrations ("
            " name text primary key, sha256 text not null, applied_at timestamptz not null default now())"
        )
        conn.execute("select pg_advisory_xact_lock(4242424242)")
        done = {r[0]: r[1] for r in conn.execute("select name, sha256 from bokbuzz_meta.schema_migrations")}
        conn.commit()
        for path in sorted(directory.glob("*.sql")):
            body = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(body.encode()).hexdigest()
            if path.name in done:
                if done[path.name] != digest:
                    raise RuntimeError(f"Migrasjonen {path.name} er endret etter at den ble kjørt")
                continue
            with conn.transaction():
                conn.execute(body)
                conn.execute(
                    "insert into bokbuzz_meta.schema_migrations (name, sha256) values (%s, %s)",
                    [path.name, digest],
                )
            applied.append(path.name)
    return applied


def main() -> None:
    url = os.environ.get("BOKBUZZ_MIGRATION_DATABASE_URL") or os.environ.get("BOKBUZZ_DATABASE_URL")
    if not url:
        sys.exit("Sett BOKBUZZ_MIGRATION_DATABASE_URL")
    for name in migrate(url):
        print(f"Kjørte {name}")


if __name__ == "__main__":
    main()
