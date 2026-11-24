"""Testoppsett: ekte Postgres (lokalt eller i CI), migrasjoner kjøres én gang.
Hver test lager egne selskaper, så testene trenger ingen opprydding."""

from __future__ import annotations

import os
import random
import time
import uuid
from collections.abc import Iterator
from datetime import date

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from bokbuzz.ai.base import ModelRouter
from bokbuzz.ai.fake import FakeModel
from bokbuzz.api.app import create_app
from bokbuzz.api.deps import Services
from bokbuzz.auth import TokenVerifier
from bokbuzz.config import Settings
from bokbuzz.db import Database
from bokbuzz.documents.storage import LocalStorage
from bokbuzz.ledger import service as ledger
from bokbuzz.ledger.models import DraftLine, VoucherDraft
from bokbuzz.ledger.money import vat_amount
from bokbuzz.migrate import migrate

DB_URL = os.environ.get("BOKBUZZ_TEST_DATABASE_URL",
                        "postgresql://postgres:postgres@localhost:5432/bokbuzz_test")
JWT_SECRET = "test-secret-som-er-lang-nok-for-hs256-signering"


def random_orgnr() -> str:
    weights = [3, 2, 7, 6, 5, 4, 3, 2]
    while True:
        base = [random.randint(0, 9) for _ in range(8)]
        base[0] = random.randint(8, 9)
        rest = sum(d * w for d, w in zip(base, weights, strict=True)) % 11
        check = 0 if rest == 0 else 11 - rest
        if check != 10:
            return "".join(map(str, base)) + str(check)


@pytest.fixture(scope="session")
def admin_url() -> str:
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("drop schema if exists bokbuzz cascade")
        conn.execute("drop schema if exists bokbuzz_meta cascade")
    migrate(DB_URL)
    return DB_URL


@pytest.fixture(scope="session")
def app_db(admin_url) -> Iterator[Database]:
    db = Database(admin_url, "bokbuzz_app", max_size=20)
    yield db
    db.close()


@pytest.fixture(scope="session")
def worker_db(admin_url) -> Iterator[Database]:
    db = Database(admin_url, "bokbuzz_worker", max_size=4)
    yield db
    db.close()


@pytest.fixture
def admin(admin_url) -> Iterator[psycopg.Connection]:
    """Superbruker-forbindelse, bare for å simulere angrep og manipulasjon."""
    with psycopg.connect(admin_url, autocommit=True, row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(environment="test", database_url=DB_URL, supabase_jwt_secret=JWT_SECRET,
                    local_storage_dir=str(tmp_path / "docs"), require_mfa=True, max_upload_bytes=200_000)


@pytest.fixture
def storage(settings) -> LocalStorage:
    return LocalStorage(settings.local_storage_dir)


@pytest.fixture
def router() -> ModelRouter:
    return ModelRouter(default=FakeModel("fake-default"), escalation=FakeModel("fake-escalation"))


@pytest.fixture
def client(settings, app_db, storage) -> TestClient:
    app = create_app(Services(settings=settings, db=app_db, storage=storage,
                              verifier=TokenVerifier(settings)))
    return TestClient(app)


def token_for(user_id: uuid.UUID, aal: str = "aal2") -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "aud": "authenticated", "aal": aal, "iat": now,
                       "exp": now + 3600, "role": "authenticated"}, JWT_SECRET, algorithm="HS256")


def auth(user_id: uuid.UUID, aal: str = "aal2") -> dict[str, str]:
    return {"authorization": f"Bearer {token_for(user_id, aal)}"}


def create_company(db: Database, user: uuid.UUID, year: int | None = None, *, org_form: str = "ENK",
                   modules: tuple[str, ...] = ("taxi",)) -> uuid.UUID:
    with db.tx(user) as conn:
        cid = conn.execute("select bokbuzz.create_company_v2(%s, %s, %s, %s, true) as id",
                           [random_orgnr(), "Test Taxi", org_form, list(modules)]).fetchone()["id"]
        if year is not None:
            conn.execute("select bokbuzz.open_fiscal_year(%s, %s)", [cid, year])
    return cid


def add_member(admin_conn: psycopg.Connection, company_id: uuid.UUID, user: uuid.UUID, role: str) -> None:
    admin_conn.execute("insert into bokbuzz.company_members (company_id, user_id, role) values (%s, %s, %s)",
                       [company_id, user, role])


def simple_draft(amount_ore: int = 10000, on: date = date(2026, 3, 15), vat: bool = True) -> VoucherDraft:
    """Kjøp av drivstoff: netto + 25 % MVA, betalt fra bank."""
    gross = amount_ore + (vat_amount(amount_ore, 2500) if vat else 0)
    return VoucherDraft(voucher_date=on, description="Diesel", lines=[
        DraftLine(account="7000", amount_ore=amount_ore, vat_code="1" if vat else None),
        DraftLine(account="1920", amount_ore=-gross),
    ])


def post_manual(db: Database, company: uuid.UUID, user: uuid.UUID, draft: VoucherDraft,
                key: str | None = None):
    with db.tx(user) as conn:
        approval = ledger.create_approval(conn, company_id=company, actor=user, kind="manual", request=draft)
        return ledger.post_voucher(conn, company_id=company, actor=user, request=draft,
                                   approval_id=approval, idempotency_key=key or uuid.uuid4().hex)


@pytest.fixture
def user() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def company(app_db, user) -> uuid.UUID:
    return create_company(app_db, user, year=2026)


# Minimal gyldig JPEG (bare magiske bytes + litt innhold) for opplastingstester.
def fake_jpeg(seed: str = "a") -> bytes:
    return b"\xff\xd8\xff\xe0" + seed.encode() * 50 + b"\xff\xd9"
