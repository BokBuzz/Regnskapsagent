-- 0003_advisor_fixes.sql
-- Rettelser etter Supabase sine advisors på nytt prosjekt (2026-11-21).

-- Sikkerhet (lint 0011): fast search_path på alle funksjoner, slik at en rolle
-- ikke kan skygge for innebygde funksjoner via egen search_path.
alter function bokbuzz.current_user_id() set search_path = pg_catalog, pg_temp;
alter function bokbuzz.reject_modification() set search_path = pg_catalog, pg_temp;
alter function bokbuzz.guard_period_update() set search_path = pg_catalog, pg_temp;
alter function bokbuzz.guard_document_update() set search_path = pg_catalog, pg_temp;
alter function bokbuzz.check_voucher_balanced() set search_path = pg_catalog, pg_temp;
alter function bokbuzz.check_period_open() set search_path = pg_catalog, pg_temp;
alter function bokbuzz.audit_hash(text, uuid, bigint, uuid, text, text, text, jsonb, timestamptz)
  set search_path = pg_catalog, pg_temp;
alter function bokbuzz.verify_audit_chain(uuid) set search_path = pg_catalog, pg_temp;

-- Ytelse (lint 0001): indekser for fremmednøkler på kundetabellene.
-- Fremmednøkler mot oppslagstabellene vat_codes slettes aldri og får ingen indeks.
create index proposals_company_document on bokbuzz.proposals (company_id, document_id);
create index review_sessions_company_proposal on bokbuzz.review_sessions (company_id, proposal_id);
create index approvals_company_proposal on bokbuzz.approvals (company_id, proposal_id);
create index approvals_company_review_session on bokbuzz.approvals (company_id, review_session_id);
create index vouchers_company_document on bokbuzz.vouchers (company_id, document_id);
create index vouchers_company_approval on bokbuzz.vouchers (company_id, approval_id);
create index vouchers_company_reverses on bokbuzz.vouchers (company_id, reverses_voucher_id);
create index voucher_lines_company_voucher on bokbuzz.voucher_lines (company_id, voucher_id);
create index jobs_company on bokbuzz.jobs (company_id);
