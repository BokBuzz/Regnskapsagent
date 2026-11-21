-- 0001_core.sql
-- Grunnskjema for Bokbuzz: selskaper, roller, kontoplan, MVA-koder, perioder,
-- dokumenter, hovedbok, forslag, godkjenninger, jobbkø og revisjonslogg.
--
-- Prinsipper (se redesign-dokumentet):
--   * Alt ligger i eget skjema "bokbuzz", som ikke eksponeres av Supabase sitt REST-API.
--   * Beløp lagres som heltall i øre (bigint). Debet er positivt, kredit negativt.
--   * Databasen er siste forsvarslinje: balansesjekk, uforanderlige bilag,
--     lukkede perioder og ingen UPDATE/DELETE/TRUNCATE for app-rollene.
--   * RLS per selskap for app-rollen. Arbeideren har egen rolle.

create schema if not exists bokbuzz;

-- ---------------------------------------------------------------------------
-- Roller. Innloggingsrollene (de som står i DATABASE_URL) opprettes av eier
-- og gis medlemskap i disse rollene. Se docs/OPPSETT.md.
-- ---------------------------------------------------------------------------
do $$
begin
  if not exists (select from pg_roles where rolname = 'bokbuzz_app') then
    create role bokbuzz_app nologin;
  end if;
  if not exists (select from pg_roles where rolname = 'bokbuzz_worker') then
    create role bokbuzz_worker nologin;
  end if;
end $$;

revoke all on schema bokbuzz from public;
grant usage on schema bokbuzz to bokbuzz_app, bokbuzz_worker;

-- ---------------------------------------------------------------------------
-- Hjelpefunksjoner
-- ---------------------------------------------------------------------------
create function bokbuzz.current_user_id() returns uuid
language sql stable as $$
  select nullif(current_setting('app.user_id', true), '')::uuid
$$;

create function bokbuzz.reject_modification() returns trigger
language plpgsql as $$
begin
  raise exception 'Tabellen % er uforanderlig. Rettelser gjøres med nytt bilag.', tg_table_name
    using errcode = 'P0001', hint = 'immutable';
end $$;

-- ---------------------------------------------------------------------------
-- Selskaper og roller
-- ---------------------------------------------------------------------------
create table bokbuzz.companies (
  id             uuid primary key default gen_random_uuid(),
  orgnr          text not null unique check (orgnr ~ '^[0-9]{9}$'),
  name           text not null check (length(name) between 1 and 200),
  vat_registered boolean not null default true,
  vat_term       text not null default 'bimonthly' check (vat_term in ('bimonthly', 'annual')),
  created_at     timestamptz not null default now()
);

create table bokbuzz.company_members (
  company_id uuid not null references bokbuzz.companies(id),
  user_id    uuid not null,
  role       text not null check (role in ('owner', 'accountant', 'reader', 'support')),
  created_at timestamptz not null default now(),
  primary key (company_id, user_id)
);

-- Selskapene innlogget bruker er medlem av. SECURITY DEFINER slik at RLS på
-- company_members ikke gir rekursjon.
create function bokbuzz.my_company_ids() returns setof uuid
language sql stable security definer
set search_path = pg_catalog, pg_temp as $$
  select company_id from bokbuzz.company_members where user_id = bokbuzz.current_user_id()
$$;

-- ---------------------------------------------------------------------------
-- MVA-koder (SAF-T standard MVA-koder) og satser med gyldighet
-- ---------------------------------------------------------------------------
create table bokbuzz.vat_codes (
  code           text primary key,          -- SAF-T StandardTaxCode
  description    text not null,
  direction      text not null check (direction in ('input', 'output', 'none')),
  ledger_account text,                      -- konto MVA-linjen føres på
  check ((direction = 'none') = (ledger_account is null))
);

create table bokbuzz.vat_rates (
  code       text not null references bokbuzz.vat_codes(code),
  rate_bp    integer not null check (rate_bp between 0 and 10000), -- basispunkter, 25 % = 2500
  valid_from date not null,
  valid_to   date,
  primary key (code, valid_from),
  check (valid_to is null or valid_to >= valid_from)
);

-- ---------------------------------------------------------------------------
-- Kontoplan: maler (NS 4102) og selskapets egne kontoer
-- ---------------------------------------------------------------------------
create table bokbuzz.account_templates (
  template              text not null,
  number                text not null check (number ~ '^[0-9]{4,6}$'),
  name                  text not null,
  account_type          text not null check (account_type in ('asset', 'liability', 'equity', 'income', 'expense')),
  saft_standard_account text not null,     -- SAF-T StandardAccountID
  grouping_code         text,              -- næringsspesifikasjon (fylles i fase 2)
  default_vat_code      text references bokbuzz.vat_codes(code),
  primary key (template, number)
);

create table bokbuzz.accounts (
  company_id            uuid not null references bokbuzz.companies(id),
  number                text not null check (number ~ '^[0-9]{4,6}$'),
  name                  text not null,
  account_type          text not null check (account_type in ('asset', 'liability', 'equity', 'income', 'expense')),
  saft_standard_account text not null,
  grouping_code         text,
  default_vat_code      text references bokbuzz.vat_codes(code),
  active_from           date not null default date '1900-01-01',
  active_to             date,
  primary key (company_id, number),
  check (active_to is null or active_to >= active_from)
);

-- ---------------------------------------------------------------------------
-- Perioder og bilagsnummer
-- ---------------------------------------------------------------------------
create table bokbuzz.periods (
  company_id uuid not null references bokbuzz.companies(id),
  year       integer not null check (year between 2000 and 2100),
  month      integer not null check (month between 1 and 12),
  status     text not null default 'open' check (status in ('open', 'closed')),
  closed_at  timestamptz,
  closed_by  uuid,
  primary key (company_id, year, month),
  check ((status = 'closed') = (closed_at is not null))
);

-- En lukket periode kan aldri åpnes igjen.
create function bokbuzz.guard_period_update() returns trigger
language plpgsql as $$
begin
  if old.status = 'closed' then
    raise exception 'Perioden %-% er lukket og kan ikke endres', old.year, old.month
      using errcode = 'P0001', hint = 'period_closed';
  end if;
  if new.company_id <> old.company_id or new.year <> old.year or new.month <> old.month then
    raise exception 'Periodens nøkkel kan ikke endres' using errcode = 'P0001';
  end if;
  return new;
end $$;

create trigger periods_guard before update on bokbuzz.periods
  for each row execute function bokbuzz.guard_period_update();
create trigger periods_no_delete before delete on bokbuzz.periods
  for each row execute function bokbuzz.reject_modification();

create table bokbuzz.voucher_counters (
  company_id  uuid not null references bokbuzz.companies(id),
  year        integer not null,
  series      text not null,
  next_number bigint not null default 1 check (next_number >= 1),
  primary key (company_id, year, series)
);

-- ---------------------------------------------------------------------------
-- Dokumenter (originalbilag). Filen ligger i låst objektlagring.
-- ---------------------------------------------------------------------------
create table bokbuzz.documents (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null references bokbuzz.companies(id),
  sha256            text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  original_filename text,
  mime_type         text not null,
  size_bytes        bigint not null check (size_bytes > 0),
  storage_key       text not null,
  status            text not null default 'received'
                    check (status in ('received', 'extracted', 'proposed', 'approved', 'posted')),
  uploaded_by       uuid not null,
  created_at        timestamptz not null default now(),
  unique (company_id, sha256),
  unique (company_id, id)
);

-- Statusen kan bare flytte ett steg. Tillatte steg tilbake: avvist forslag
-- (proposed -> extracted) og reversert bilag (posted -> approved).
create function bokbuzz.guard_document_update() returns trigger
language plpgsql as $$
begin
  if new.id <> old.id or new.company_id <> old.company_id or new.sha256 <> old.sha256
     or new.storage_key <> old.storage_key or new.size_bytes <> old.size_bytes
     or new.mime_type <> old.mime_type or new.uploaded_by <> old.uploaded_by then
    raise exception 'Dokumentets innhold og eier kan ikke endres' using errcode = 'P0001', hint = 'immutable';
  end if;
  if new.status <> old.status and not (
       (old.status, new.status) in (
         ('received', 'extracted'), ('extracted', 'proposed'), ('proposed', 'approved'),
         ('approved', 'posted'), ('proposed', 'extracted'), ('posted', 'approved'))) then
    raise exception 'Ugyldig statusovergang for dokument: % -> %', old.status, new.status
      using errcode = 'P0001', hint = 'status_transition';
  end if;
  return new;
end $$;

create trigger documents_guard before update on bokbuzz.documents
  for each row execute function bokbuzz.guard_document_update();
create trigger documents_no_delete before delete on bokbuzz.documents
  for each row execute function bokbuzz.reject_modification();
create trigger documents_no_truncate before truncate on bokbuzz.documents
  for each statement execute function bokbuzz.reject_modification();

-- ---------------------------------------------------------------------------
-- Forslag, gjennomgang og godkjenning
-- ---------------------------------------------------------------------------
create table bokbuzz.proposals (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null references bokbuzz.companies(id),
  document_id       uuid not null,
  status            text not null default 'pending'
                    check (status in ('pending', 'approved', 'rejected', 'needs_manual')),
  model             text,
  prompt_version    text not null,
  rules_version     text not null,
  input_hash        text not null,
  extraction        jsonb,
  draft             jsonb,
  draft_hash        text,
  validation_errors jsonb not null default '[]'::jsonb,
  warnings          jsonb not null default '[]'::jsonb,
  escalated         boolean not null default false,
  usage             jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now(),
  decided_by        uuid,
  decided_at        timestamptz,
  decision_note     text,
  voucher_id        uuid,
  unique (company_id, id),
  unique (document_id, input_hash),
  foreign key (company_id, document_id) references bokbuzz.documents(company_id, id),
  check ((draft is null) = (draft_hash is null)),
  check (status <> 'pending' or draft is not null)
);

-- Klikk 1: brukeren åpner forslaget ved siden av originalen.
create table bokbuzz.review_sessions (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references bokbuzz.companies(id),
  proposal_id uuid not null,
  user_id     uuid not null,
  token_hash  text not null unique,
  draft_hash  text not null,
  opened_at   timestamptz not null default now(),
  expires_at  timestamptz not null,
  used_at     timestamptz,
  unique (company_id, id),
  foreign key (company_id, proposal_id) references bokbuzz.proposals(company_id, id)
);

-- Klikk 2: godkjenning av et bestemt innhold (content_hash).
create table bokbuzz.approvals (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null references bokbuzz.companies(id),
  kind              text not null check (kind in ('proposal', 'manual', 'reversal')),
  proposal_id       uuid,
  review_session_id uuid,
  approved_by       uuid not null,
  content_hash      text not null,
  created_at        timestamptz not null default now(),
  used_at           timestamptz,
  unique (company_id, id),
  foreign key (company_id, proposal_id) references bokbuzz.proposals(company_id, id),
  foreign key (company_id, review_session_id) references bokbuzz.review_sessions(company_id, id),
  -- Et KI-forslag kan aldri godkjennes uten en forutgående gjennomgang (to klikk).
  check (kind <> 'proposal' or (proposal_id is not null and review_session_id is not null))
);

-- ---------------------------------------------------------------------------
-- Hovedbok
-- ---------------------------------------------------------------------------
create table bokbuzz.vouchers (
  id                  uuid primary key default gen_random_uuid(),
  company_id          uuid not null references bokbuzz.companies(id),
  year                integer not null,
  series              text not null check (series ~ '^[A-Z]{1,3}$'),
  number              bigint not null check (number >= 1),
  voucher_date        date not null,
  description         text not null check (length(description) between 1 and 500),
  document_id         uuid,
  idempotency_key     text not null check (length(idempotency_key) between 1 and 200),
  content_hash        text not null,
  approval_id         uuid not null,
  reverses_voucher_id uuid,
  reversal_reason     text,
  posted_by           uuid not null,
  line_count          integer not null check (line_count >= 2),
  posted_at           timestamptz not null default now(),
  unique (company_id, id),
  unique (company_id, year, series, number),
  unique (company_id, idempotency_key),
  unique (approval_id),
  unique (reverses_voucher_id),
  foreign key (company_id, document_id) references bokbuzz.documents(company_id, id),
  foreign key (company_id, approval_id) references bokbuzz.approvals(company_id, id),
  foreign key (company_id, reverses_voucher_id) references bokbuzz.vouchers(company_id, id),
  check (year = extract(year from voucher_date)::integer),
  check ((reverses_voucher_id is null) = (reversal_reason is null))
);

create table bokbuzz.voucher_lines (
  voucher_id            uuid not null,
  company_id            uuid not null,
  line_no               integer not null check (line_no >= 1),
  account_number        text not null,
  amount_ore            bigint not null check (amount_ore <> 0),  -- NOK, debet +, kredit -
  currency              char(3) not null default 'NOK' check (currency ~ '^[A-Z]{3}$'),
  currency_amount_minor bigint,
  exchange_rate         numeric(18, 8),
  vat_code              text references bokbuzz.vat_codes(code),
  vat_base_line_no      integer,   -- satt på MVA-linjer: hvilken linje MVA-en gjelder
  description           text,
  primary key (voucher_id, line_no),
  foreign key (company_id, voucher_id) references bokbuzz.vouchers(company_id, id),
  foreign key (company_id, account_number) references bokbuzz.accounts(company_id, number),
  check (currency = 'NOK' or (currency_amount_minor is not null and exchange_rate is not null))
);
create index voucher_lines_company_account on bokbuzz.voucher_lines (company_id, account_number);

-- Utsatt balansesjekk: ved commit må hvert bilag ha nøyaktig line_count linjer og sum 0.
create function bokbuzz.check_voucher_balanced() returns trigger
language plpgsql as $$
declare
  vid uuid;
  total bigint;
  n integer;
  expected integer;
begin
  if tg_table_name = 'vouchers' then vid := new.id; else vid := new.voucher_id; end if;
  select coalesce(sum(amount_ore), 0), count(*) into total, n
    from bokbuzz.voucher_lines where voucher_id = vid;
  select line_count into expected from bokbuzz.vouchers where id = vid;
  -- line_count er låst på bilaget, så linjer kan ikke legges til senere.
  if n < 2 or n <> expected then
    raise exception 'Bilag % har % linjer, forventet %', vid, n, expected
      using errcode = '23514', hint = 'unbalanced';
  end if;
  if total <> 0 then
    raise exception 'Bilag % er ikke i balanse (differanse % øre)', vid, total
      using errcode = '23514', hint = 'unbalanced';
  end if;
  return null;
end $$;

create constraint trigger vouchers_balanced after insert on bokbuzz.vouchers
  deferrable initially deferred for each row execute function bokbuzz.check_voucher_balanced();
create constraint trigger voucher_lines_balanced after insert on bokbuzz.voucher_lines
  deferrable initially deferred for each row execute function bokbuzz.check_voucher_balanced();

-- Bokføring bare i åpen periode.
create function bokbuzz.check_period_open() returns trigger
language plpgsql as $$
begin
  if not exists (
    select 1 from bokbuzz.periods
     where company_id = new.company_id
       and year = extract(year from new.voucher_date)::integer
       and month = extract(month from new.voucher_date)::integer
       and status = 'open') then
    raise exception 'Perioden for % er ikke åpen', new.voucher_date
      using errcode = 'P0001', hint = 'period_closed';
  end if;
  return new;
end $$;

create trigger vouchers_period_open before insert on bokbuzz.vouchers
  for each row execute function bokbuzz.check_period_open();

create trigger vouchers_immutable before update or delete on bokbuzz.vouchers
  for each row execute function bokbuzz.reject_modification();
create trigger voucher_lines_immutable before update or delete on bokbuzz.voucher_lines
  for each row execute function bokbuzz.reject_modification();
create trigger vouchers_no_truncate before truncate on bokbuzz.vouchers
  for each statement execute function bokbuzz.reject_modification();
create trigger voucher_lines_no_truncate before truncate on bokbuzz.voucher_lines
  for each statement execute function bokbuzz.reject_modification();

-- ---------------------------------------------------------------------------
-- Revisjonslogg med hash-kjede per selskap (append-only)
-- ---------------------------------------------------------------------------
create table bokbuzz.audit_events (
  id          bigint generated always as identity primary key,
  company_id  uuid not null references bokbuzz.companies(id),
  seq         bigint not null,
  actor       uuid,
  event_type  text not null,
  entity_type text,
  entity_id   text,
  payload     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default clock_timestamp(),
  prev_hash   text not null,
  hash        text not null,
  unique (company_id, seq)
);

create function bokbuzz.audit_hash(
  p_prev text, p_company uuid, p_seq bigint, p_actor uuid, p_event_type text,
  p_entity_type text, p_entity_id text, p_payload jsonb, p_created_at timestamptz
) returns text
language sql immutable as $$
  select encode(sha256(convert_to(concat_ws('|',
    p_prev, p_company::text, p_seq::text, coalesce(p_actor::text, ''), p_event_type,
    coalesce(p_entity_type, ''), coalesce(p_entity_id, ''), p_payload::text,
    (extract(epoch from p_created_at) * 1000000)::bigint::text), 'UTF8')), 'hex')
$$;

create function bokbuzz.audit_chain() returns trigger
language plpgsql security definer
set search_path = pg_catalog, pg_temp as $$
declare
  last_seq bigint;
  last_hash text;
begin
  perform pg_advisory_xact_lock(hashtextextended('audit:' || new.company_id::text, 0));
  select seq, hash into last_seq, last_hash
    from bokbuzz.audit_events where company_id = new.company_id
   order by seq desc limit 1;
  new.seq := coalesce(last_seq, 0) + 1;
  new.prev_hash := coalesce(last_hash, repeat('0', 64));
  new.created_at := clock_timestamp();
  new.hash := bokbuzz.audit_hash(new.prev_hash, new.company_id, new.seq, new.actor, new.event_type,
                                 new.entity_type, new.entity_id, new.payload, new.created_at);
  return new;
end $$;

create trigger audit_events_chain before insert on bokbuzz.audit_events
  for each row execute function bokbuzz.audit_chain();
create trigger audit_events_immutable before update or delete on bokbuzz.audit_events
  for each row execute function bokbuzz.reject_modification();
create trigger audit_events_no_truncate before truncate on bokbuzz.audit_events
  for each statement execute function bokbuzz.reject_modification();

-- Returnerer første seq der kjeden er brutt, eller null når alt stemmer.
-- SECURITY INVOKER: RLS avgjør hvilke rader kalleren ser, og app-rollen ser bare egne selskaper.
create function bokbuzz.verify_audit_chain(p_company uuid) returns bigint
language plpgsql stable as $$
declare
  r record;
  expected_prev text := repeat('0', 64);
  expected_seq bigint := 1;
begin
  for r in select * from bokbuzz.audit_events where company_id = p_company order by seq loop
    if r.seq <> expected_seq or r.prev_hash <> expected_prev
       or r.hash <> bokbuzz.audit_hash(r.prev_hash, r.company_id, r.seq, r.actor, r.event_type,
                                       r.entity_type, r.entity_id, r.payload, r.created_at) then
      return r.seq;
    end if;
    expected_prev := r.hash;
    expected_seq := expected_seq + 1;
  end loop;
  return null;
end $$;

-- ---------------------------------------------------------------------------
-- Jobbkø i databasen (FOR UPDATE SKIP LOCKED + lease)
-- ---------------------------------------------------------------------------
create table bokbuzz.jobs (
  id           bigint generated always as identity primary key,
  company_id   uuid references bokbuzz.companies(id),
  kind         text not null,
  payload      jsonb not null default '{}'::jsonb,
  dedupe_key   text unique,
  status       text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
  attempts     integer not null default 0,
  max_attempts integer not null default 5,
  run_after    timestamptz not null default now(),
  lease_until  timestamptz,
  last_error   text,
  created_at   timestamptz not null default now(),
  finished_at  timestamptz
);
create index jobs_ready on bokbuzz.jobs (run_after, id) where status in ('queued', 'running');

-- ---------------------------------------------------------------------------
-- Funksjoner for onboarding (SECURITY DEFINER, med egne tilgangssjekker)
-- ---------------------------------------------------------------------------
create function bokbuzz.open_fiscal_year(p_company uuid, p_year integer) returns void
language plpgsql security definer
set search_path = pg_catalog, pg_temp as $$
begin
  if not exists (select 1 from bokbuzz.company_members
                  where company_id = p_company and user_id = bokbuzz.current_user_id()
                    and role in ('owner', 'accountant')) then
    raise exception 'Bare eier eller regnskapsfører kan åpne regnskapsår' using errcode = '42501';
  end if;
  insert into bokbuzz.periods (company_id, year, month)
  select p_company, p_year, m from generate_series(1, 12) m
  on conflict do nothing;
  insert into bokbuzz.audit_events (company_id, actor, event_type, entity_type, entity_id, payload)
  values (p_company, bokbuzz.current_user_id(), 'fiscal_year.opened', 'company', p_company::text,
          jsonb_build_object('year', p_year));
end $$;

create function bokbuzz.create_company(p_orgnr text, p_name text, p_template text default 'taxi_enk')
returns uuid
language plpgsql security definer
set search_path = pg_catalog, pg_temp as $$
declare
  uid uuid := bokbuzz.current_user_id();
  cid uuid;
begin
  if uid is null then
    raise exception 'Ingen innlogget bruker' using errcode = '42501';
  end if;
  insert into bokbuzz.companies (orgnr, name) values (p_orgnr, p_name) returning id into cid;
  insert into bokbuzz.company_members (company_id, user_id, role) values (cid, uid, 'owner');
  insert into bokbuzz.accounts (company_id, number, name, account_type, saft_standard_account,
                                grouping_code, default_vat_code)
  select cid, number, name, account_type, saft_standard_account, grouping_code, default_vat_code
    from bokbuzz.account_templates where template = p_template;
  if not found then
    raise exception 'Ukjent kontoplanmal %', p_template using errcode = '22023';
  end if;
  insert into bokbuzz.audit_events (company_id, actor, event_type, entity_type, entity_id, payload)
  values (cid, uid, 'company.created', 'company', cid::text,
          jsonb_build_object('orgnr', p_orgnr, 'name', p_name, 'template', p_template));
  perform bokbuzz.open_fiscal_year(cid, extract(year from (now() at time zone 'Europe/Oslo'))::integer);
  return cid;
end $$;

-- ---------------------------------------------------------------------------
-- Rettigheter: minste nødvendige. Ingen DELETE eller TRUNCATE for app-rollene.
-- ---------------------------------------------------------------------------
revoke all on all tables in schema bokbuzz from public;
revoke all on all functions in schema bokbuzz from public;

grant select on all tables in schema bokbuzz to bokbuzz_app, bokbuzz_worker;
grant usage on all sequences in schema bokbuzz to bokbuzz_app, bokbuzz_worker;
grant execute on function bokbuzz.current_user_id(), bokbuzz.my_company_ids(),
  bokbuzz.audit_hash(text, uuid, bigint, uuid, text, text, text, jsonb, timestamptz),
  bokbuzz.verify_audit_chain(uuid) to bokbuzz_app, bokbuzz_worker;
grant execute on function bokbuzz.create_company(text, text, text),
  bokbuzz.open_fiscal_year(uuid, integer) to bokbuzz_app;

-- App (API-et)
grant insert on bokbuzz.documents, bokbuzz.review_sessions, bokbuzz.approvals,
  bokbuzz.vouchers, bokbuzz.voucher_lines, bokbuzz.audit_events, bokbuzz.jobs,
  bokbuzz.voucher_counters to bokbuzz_app;
grant update (status) on bokbuzz.documents to bokbuzz_app;
grant update (status, decided_by, decided_at, decision_note, voucher_id) on bokbuzz.proposals to bokbuzz_app;
grant update (used_at) on bokbuzz.review_sessions to bokbuzz_app;
grant update (used_at) on bokbuzz.approvals to bokbuzz_app;
grant update (status, closed_at, closed_by) on bokbuzz.periods to bokbuzz_app;
grant update (next_number) on bokbuzz.voucher_counters to bokbuzz_app;

-- Arbeider (jobbkø, uttrekk og forslag)
grant insert on bokbuzz.proposals, bokbuzz.audit_events, bokbuzz.jobs to bokbuzz_worker;
grant update (status) on bokbuzz.documents to bokbuzz_worker;
grant update (status, attempts, run_after, lease_until, last_error, finished_at) on bokbuzz.jobs to bokbuzz_worker;

-- ---------------------------------------------------------------------------
-- Radnivåsikkerhet (RLS): app-rollen ser bare egne selskaper.
-- ---------------------------------------------------------------------------
alter table bokbuzz.companies enable row level security;
create policy app_companies on bokbuzz.companies for all to bokbuzz_app
  using (id in (select bokbuzz.my_company_ids())) with check (id in (select bokbuzz.my_company_ids()));
create policy worker_companies on bokbuzz.companies for all to bokbuzz_worker using (true) with check (true);

do $$
declare t text;
begin
  foreach t in array array['company_members', 'accounts', 'periods', 'voucher_counters', 'documents',
                           'proposals', 'review_sessions', 'approvals', 'vouchers', 'voucher_lines',
                           'audit_events', 'jobs'] loop
    execute format('alter table bokbuzz.%I enable row level security', t);
    execute format('create policy app_tenant on bokbuzz.%I for all to bokbuzz_app '
                   'using (company_id in (select bokbuzz.my_company_ids())) '
                   'with check (company_id in (select bokbuzz.my_company_ids()))', t);
    execute format('create policy worker_all on bokbuzz.%I for all to bokbuzz_worker using (true) with check (true)', t);
  end loop;
end $$;

-- Supabase eksponerer skjemaer via REST for rollene anon/authenticated. Sørg for
-- at de aldri har tilgang hit, selv om noen legger skjemaet til i API-et.
do $$
begin
  if exists (select from pg_roles where rolname = 'anon') then
    execute 'revoke all on schema bokbuzz from anon';
    execute 'revoke all on all tables in schema bokbuzz from anon';
  end if;
  if exists (select from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on schema bokbuzz from authenticated';
    execute 'revoke all on all tables in schema bokbuzz from authenticated';
  end if;
end $$;
