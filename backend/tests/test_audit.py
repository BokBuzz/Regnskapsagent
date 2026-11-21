"""Revisjonsloggen: hash-kjede som avslører manipulasjon."""

from __future__ import annotations

from conftest import post_manual, simple_draft

from bokbuzz import audit


def test_chain_is_valid_after_activity(app_db, company, user):
    for i in range(3):
        post_manual(app_db, company, user, simple_draft(100 + i))
    with app_db.tx(user) as conn:
        assert audit.verify_chain(conn, company) is None
        events = conn.execute("select seq, event_type from bokbuzz.audit_events where company_id = %s"
                              " order by seq", [company]).fetchall()
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[0]["event_type"] == "company.created"


def test_tampered_row_is_detected(app_db, company, user, admin):
    post_manual(app_db, company, user, simple_draft())
    # En angriper med superbruker slår av vakten og endrer en hendelse.
    admin.execute("alter table bokbuzz.audit_events disable trigger audit_events_immutable")
    try:
        admin.execute("update bokbuzz.audit_events set payload = '{\"orgnr\": \"999999999\"}'"
                      " where company_id = %s and seq = 1", [company])
    finally:
        admin.execute("alter table bokbuzz.audit_events enable trigger audit_events_immutable")
    with app_db.tx(user) as conn:
        assert audit.verify_chain(conn, company) == 1


def test_deleted_row_is_detected(app_db, company, user, admin):
    post_manual(app_db, company, user, simple_draft())
    admin.execute("alter table bokbuzz.audit_events disable trigger audit_events_immutable")
    try:
        admin.execute("delete from bokbuzz.audit_events where company_id = %s and seq = 2", [company])
    finally:
        admin.execute("alter table bokbuzz.audit_events enable trigger audit_events_immutable")
    with app_db.tx(user) as conn:
        assert audit.verify_chain(conn, company) == 3
