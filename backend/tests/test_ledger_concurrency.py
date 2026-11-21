"""100 samtidige bokføringer gir 100 unike bilagsnummer uten hull."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from conftest import post_manual, simple_draft


def test_concurrent_posting_gives_gapless_numbers(app_db, company, user):
    def post(i: int) -> int:
        return post_manual(app_db, company, user, simple_draft(100 + i), key=f"c{i}").number

    with ThreadPoolExecutor(max_workers=16) as pool:
        numbers = list(pool.map(post, range(100)))
    assert sorted(numbers) == list(range(1, 101))


def test_concurrent_same_idempotency_key_gives_one_voucher(app_db, company, user):
    draft = simple_draft(4242)

    def post(_: int):
        return post_manual(app_db, company, user, draft, key="same").id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = set(pool.map(post, range(20)))
    assert len(ids) == 1
