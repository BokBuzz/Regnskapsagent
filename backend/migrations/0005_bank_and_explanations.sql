-- 0005_bank_and_explanations.sql
-- Bankagent v1: kontoutskrifter (CAMT.053), banktransaksjoner, avstemming mot hovedboken
-- og regelstyrte forslag for banklinjer som banken selv dokumenterer (gebyr og renter).
-- I tillegg: forklaring («Hvorfor?») på alle forslag.
--
-- Prinsipper som før: bankdata er uforanderlige, avstemming endrer aldri hovedboken,
-- og bokføring skjer bare gjennom godkjenning i to klikk.

-- ---------------------------------------------------------------------------
-- Bankkontoer
-- ---------------------------------------------------------------------------
create table bokbuzz.bank_accounts (
  id             uuid primary key default gen_random_uuid(),
  company_id     uuid not null references bokbuzz.companies(id),
  account_id     text not null check (account_id ~ '^[A-Z0-9]{5,34}$'),  -- kontonummer eller IBAN
  currency       char(3) not null default 'NOK' check (currency ~ '^[A-Z]{3}$'),
  ledger_account text not null default '1920',
  name           text,
  created_at     timestamptz not null default now(),
  unique (company_id, account_id),
  unique (company_id, id),
  foreign key (company_id, ledger_account) references bokbuzz.accounts(company_id, number)
);

-- ---------------------------------------------------------------------------
-- Kontoutskrifter. Filen lagres innholdsadressert som originalbilagene.
-- ---------------------------------------------------------------------------
create table bokbuzz.bank_statements (
  id                  uuid primary key default gen_random_uuid(),
  company_id          uuid not null references bokbuzz.companies(id),
  bank_account_id     uuid not null,
  sha256              text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  storage_key         text not null,
  original_filename   text,
  statement_ref       text,
  from_date           date,
  to_date             date,
  opening_balance_ore bigint,
  closing_balance_ore bigint,
  entry_count         integer not null check (entry_count >= 0),
  new_count           integer not null check (new_count >= 0),
  balance_ok          boolean,          -- null når banken ikke oppgir begge saldoene
  imported_by         uuid not null,
  created_at          timestamptz not null default now(),
  unique (company_id, sha256),
  unique (company_id, id),
  foreign key (company_id, bank_account_id) references bokbuzz.bank_accounts(company_id, id)
);

create table bokbuzz.bank_transactions (
  id                   uuid primary key default gen_random_uuid(),
  company_id           uuid not null references bokbuzz.companies(id),
  bank_account_id      uuid not null,
  statement_id         uuid not null,
  fingerprint          text not null,   -- stabil nøkkel, så overlappende utskrifter ikke gir duplikater
  booking_date         date not null,
  value_date           date,
  amount_ore           bigint not null check (amount_ore <> 0),  -- inn +, ut -
  currency             char(3) not null default 'NOK',
  counterparty_name    text,
  counterparty_account text,
  reference            text,            -- KID eller annen strukturert referanse
  end_to_end_id        text,
  description          text,
  bank_ref             text,            -- bankens referanse (AcctSvcrRef)
  bank_tx_code         text,            -- f.eks. PMNT/CCRD/POSD eller ACMT/MDOP/CHRG
  created_at           timestamptz not null default now(),
  unique (company_id, bank_account_id, fingerprint),
  unique (company_id, id),
  foreign key (company_id, bank_account_id) references bokbuzz.bank_accounts(company_id, id),
  foreign key (company_id, statement_id) references bokbuzz.bank_statements(company_id, id)
);
create index bank_transactions_company_date on bokbuzz.bank_transactions (company_id, booking_date);
create index bank_transactions_company_statement on bokbuzz.bank_transactions (company_id, statement_id);

create trigger bank_statements_immutable before update or delete on bokbuzz.bank_statements
  for each row execute function bokbuzz.reject_modification();
create trigger bank_transactions_immutable before update or delete on bokbuzz.bank_transactions
  for each row execute function bokbuzz.reject_modification();
create trigger bank_statements_no_truncate before truncate on bokbuzz.bank_statements
  for each statement execute function bokbuzz.reject_modification();
create trigger bank_transactions_no_truncate before truncate on bokbuzz.bank_transactions
  for each statement execute function bokbuzz.reject_modification();

-- ---------------------------------------------------------------------------
-- Avstemming: kobling mellom banklinje og hovedbokslinje på bankkontoen.
-- Systemet foreslår (suggested); brukeren bekrefter eller avviser.
-- ---------------------------------------------------------------------------
create table bokbuzz.bank_matches (
  id             uuid primary key default gen_random_uuid(),
  company_id     uuid not null references bokbuzz.companies(id),
  transaction_id uuid not null,
  voucher_id     uuid not null,
  line_no        integer not null,
  status         text not null default 'suggested' check (status in ('suggested', 'confirmed', 'rejected')),
  method         text not null,       -- exact_unique, closest_date, from_proposal
  explanation    text not null,
  created_at     timestamptz not null default now(),
  decided_by     uuid,
  decided_at     timestamptz,
  unique (company_id, id),
  foreign key (company_id, transaction_id) references bokbuzz.bank_transactions(company_id, id),
  foreign key (company_id, voucher_id) references bokbuzz.vouchers(company_id, id),
  foreign key (voucher_id, line_no) references bokbuzz.voucher_lines(voucher_id, line_no),
  check ((status = 'suggested') = (decided_at is null))
);
-- En banklinje og en hovedbokslinje kan ha høyst én aktiv kobling hver.
create unique index bank_matches_one_per_tx on bokbuzz.bank_matches (transaction_id)
  where status in ('suggested', 'confirmed');
create unique index bank_matches_one_per_line on bokbuzz.bank_matches (voucher_id, line_no)
  where status in ('suggested', 'confirmed');
-- Et avvist par foreslås aldri igjen.
create unique index bank_matches_pair on bokbuzz.bank_matches (transaction_id, voucher_id, line_no);
create index bank_matches_company on bokbuzz.bank_matches (company_id);

-- Bare suggested -> confirmed/rejected er lov, og bare status og beslutning kan endres.
create function bokbuzz.guard_bank_match_update() returns trigger
language plpgsql
set search_path = pg_catalog, pg_temp as $$
begin
  if new.transaction_id <> old.transaction_id or new.voucher_id <> old.voucher_id
     or new.line_no <> old.line_no or new.company_id <> old.company_id or new.method <> old.method then
    raise exception 'Koblingen kan ikke flyttes' using errcode = 'P0001', hint = 'immutable';
  end if;
  if old.status <> 'suggested' and new.status <> old.status then
    raise exception 'Koblingen er allerede behandlet' using errcode = 'P0001', hint = 'status_transition';
  end if;
  return new;
end $$;

create trigger bank_matches_guard before update on bokbuzz.bank_matches
  for each row execute function bokbuzz.guard_bank_match_update();
create trigger bank_matches_no_delete before delete on bokbuzz.bank_matches
  for each row execute function bokbuzz.reject_modification();

-- ---------------------------------------------------------------------------
-- Forslag kan nå komme fra en banklinje i stedet for et dokument.
-- ---------------------------------------------------------------------------
alter table bokbuzz.proposals
  alter column document_id drop not null,
  add column bank_transaction_id uuid,
  add column explanation text check (explanation is null or length(explanation) <= 1000),
  add constraint proposals_bank_tx_fk foreign key (company_id, bank_transaction_id)
    references bokbuzz.bank_transactions(company_id, id),
  add constraint proposals_one_source check ((document_id is null) <> (bank_transaction_id is null));
create unique index proposals_bank_tx_input on bokbuzz.proposals (bank_transaction_id, input_hash)
  where bank_transaction_id is not null;
create index proposals_company_bank_tx on bokbuzz.proposals (company_id, bank_transaction_id);

-- ---------------------------------------------------------------------------
-- Rettigheter og RLS
-- ---------------------------------------------------------------------------
grant select on bokbuzz.bank_accounts, bokbuzz.bank_statements, bokbuzz.bank_transactions,
  bokbuzz.bank_matches to bokbuzz_app, bokbuzz_worker;
grant insert on bokbuzz.bank_accounts, bokbuzz.bank_statements, bokbuzz.bank_transactions,
  bokbuzz.bank_matches to bokbuzz_app;
grant update (status, decided_by, decided_at) on bokbuzz.bank_matches to bokbuzz_app;
grant update (ledger_account, name) on bokbuzz.bank_accounts to bokbuzz_app;
grant insert on bokbuzz.bank_matches to bokbuzz_worker;

do $$
declare t text;
begin
  foreach t in array array['bank_accounts', 'bank_statements', 'bank_transactions', 'bank_matches'] loop
    execute format('alter table bokbuzz.%I enable row level security', t);
    execute format('create policy app_tenant on bokbuzz.%I for all to bokbuzz_app '
                   'using (company_id in (select bokbuzz.my_company_ids())) '
                   'with check (company_id in (select bokbuzz.my_company_ids()))', t);
    execute format('create policy worker_all on bokbuzz.%I for all to bokbuzz_worker using (true) with check (true)', t);
  end loop;
end $$;

do $$
begin
  if exists (select from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema bokbuzz from anon';
  end if;
  if exists (select from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on all tables in schema bokbuzz from authenticated';
  end if;
end $$;
