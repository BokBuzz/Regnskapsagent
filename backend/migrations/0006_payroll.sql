-- 0006_payroll.sql
-- Lønn, steg L0 (se docs/LONN.md): ansatte, lønnsinnstillinger, lønnskjøringer med linjer per ansatt,
-- satser for arbeidsgiveravgift med gyldighet, og kontoene lønn trenger.
--
-- Lønnskjøringen bokføres gjennom post_voucher som alt annet, etter kundens godkjenning.
-- Godkjente kjøringer og linjene deres kan ikke endres.
--
-- VERIFISER: satsene for arbeidsgiveravgift og feriepenger må kontrolleres mot Skatteetaten
-- og godkjennes av regnskapsfører før første ekte lønnskjøring.

-- ---------------------------------------------------------------------------
-- Kontoer lønn trenger (malene og eksisterende ENK/AS-selskaper)
-- ---------------------------------------------------------------------------
insert into bokbuzz.account_templates
  (template, number, name, account_type, saft_standard_account, default_vat_code)
select t.template, a.number, a.name, a.account_type, a.number, null
  from (values ('1950', 'Bankinnskudd for skattetrekk', 'asset'),
               ('2930', 'Skyldig lønn', 'liability'),
               ('2785', 'Skyldig arbeidsgiveravgift av påløpte feriepenger', 'liability'),
               ('5420', 'Arbeidsgiveravgift av påløpte feriepenger', 'expense')) a(number, name, account_type)
 cross join (values ('enk'), ('as')) t(template)
on conflict do nothing;

insert into bokbuzz.accounts (company_id, number, name, account_type, saft_standard_account)
select c.id, t.number, t.name, t.account_type, t.saft_standard_account
  from bokbuzz.companies c
  join bokbuzz.account_templates t on t.template = lower(c.org_form)
 where t.number in ('1950', '2930', '2785', '5420')
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- Satser for arbeidsgiveravgift per sone (basispunkter), med gyldighet
-- ---------------------------------------------------------------------------
create table bokbuzz.aga_rates (
  zone       text not null check (zone in ('1', '1a', '2', '3', '4', '4a', '5')),
  rate_bp    integer not null check (rate_bp between 0 and 10000),
  valid_from date not null,
  valid_to   date,
  primary key (zone, valid_from),
  check (valid_to is null or valid_to >= valid_from)
);
insert into bokbuzz.aga_rates (zone, rate_bp, valid_from) values
  ('1', 1410, date '2007-01-01'), ('1a', 1060, date '2007-01-01'), ('2', 1060, date '2007-01-01'),
  ('3', 640, date '2007-01-01'), ('4', 510, date '2007-01-01'), ('4a', 790, date '2007-01-01'),
  ('5', 0, date '2007-01-01');

-- ---------------------------------------------------------------------------
-- Lønnsinnstillinger per selskap
-- ---------------------------------------------------------------------------
create table bokbuzz.payroll_settings (
  company_id              uuid primary key references bokbuzz.companies(id),
  aga_zone                text not null default '1' check (aga_zone in ('1', '1a', '2', '3', '4', '4a', '5')),
  holiday_rate_bp         integer not null default 1020 check (holiday_rate_bp in (1020, 1200)),
  pay_from_account        text not null check (pay_from_account ~ '^[0-9]{11}$'),   -- driftskonto
  tax_withholding_account text check (tax_withholding_account ~ '^[0-9]{11}$'),      -- skattetrekkskonto
  kid_withholding         text check (kid_withholding ~ '^[0-9]{2,25}$'),             -- KID forskuddstrekk
  kid_aga                 text check (kid_aga ~ '^[0-9]{2,25}$'),                     -- KID arbeidsgiveravgift
  tax_authority_account   text check (tax_authority_account ~ '^[0-9]{11}$'),        -- Skatteetatens konto
  updated_at              timestamptz not null default now(),
  updated_by              uuid not null
);

-- ---------------------------------------------------------------------------
-- Ansatte
-- ---------------------------------------------------------------------------
create table bokbuzz.employees (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null references bokbuzz.companies(id),
  national_id       text not null check (national_id ~ '^[0-9]{11}$'),  -- fødselsnummer / d-nummer
  name              text not null check (length(name) between 1 and 200),
  email             text,
  bank_account      text not null check (bank_account ~ '^[0-9]{11}$'),
  position_pct_bp   integer not null default 10000 check (position_pct_bp between 1 and 10000),
  pay_type          text not null check (pay_type in ('monthly', 'hourly')),
  monthly_salary_ore bigint check (monthly_salary_ore > 0),
  hourly_rate_ore   bigint check (hourly_rate_ore > 0),
  tax_card_kind     text not null default 'percent' check (tax_card_kind in ('percent', 'table', 'none')),
  tax_percent       integer check (tax_percent between 0 and 100),
  tax_table         text check (tax_table ~ '^[0-9]{4}$'),
  start_date        date not null,
  end_date          date,
  created_at        timestamptz not null default now(),
  unique (company_id, id),
  unique (company_id, national_id),
  check (end_date is null or end_date >= start_date),
  check ((pay_type = 'monthly') = (monthly_salary_ore is not null)),
  check ((pay_type = 'hourly') = (hourly_rate_ore is not null)),
  check (tax_card_kind <> 'percent' or tax_percent is not null),
  check (tax_card_kind <> 'table' or tax_table is not null)
);

-- ---------------------------------------------------------------------------
-- Lønnskjøringer
-- ---------------------------------------------------------------------------
create table bokbuzz.payroll_runs (
  id           uuid primary key default gen_random_uuid(),
  company_id   uuid not null references bokbuzz.companies(id),
  year         integer not null check (year between 2000 and 2100),
  month        integer not null check (month between 1 and 12),
  pay_date     date not null,
  status       text not null default 'draft' check (status in ('draft', 'approved', 'cancelled')),
  aga_zone     text not null,
  aga_rate_bp  integer not null,
  holiday_rate_bp integer not null,
  content_hash text,           -- hash av bilaget kunden godkjente
  voucher_id   uuid,
  created_by   uuid not null,
  created_at   timestamptz not null default now(),
  approved_by  uuid,
  approved_at  timestamptz,
  unique (company_id, id),
  foreign key (company_id, voucher_id) references bokbuzz.vouchers(company_id, id),
  check ((status = 'approved') = (voucher_id is not null and approved_at is not null))
);
-- Én aktiv kjøring per måned (utkast eller godkjent).
create unique index payroll_runs_one_per_month on bokbuzz.payroll_runs (company_id, year, month)
  where status in ('draft', 'approved');

create table bokbuzz.payroll_lines (
  run_id          uuid not null,
  company_id      uuid not null,
  employee_id     uuid not null,
  hours_x100      integer check (hours_x100 >= 0),      -- timer * 100 for timelønn
  base_ore        bigint not null check (base_ore >= 0), -- fastlønn eller timer * sats
  bonus_ore       bigint not null default 0 check (bonus_ore >= 0),
  gross_ore       bigint not null check (gross_ore >= 0),
  tax_ore         bigint not null check (tax_ore >= 0),
  tax_manual      boolean not null default false,
  holiday_pay_ore bigint not null check (holiday_pay_ore >= 0),  -- opptjente feriepenger
  aga_ore         bigint not null check (aga_ore >= 0),
  aga_holiday_ore bigint not null check (aga_holiday_ore >= 0),
  net_ore         bigint not null,
  note            text,
  primary key (run_id, employee_id),
  foreign key (company_id, run_id) references bokbuzz.payroll_runs(company_id, id),
  foreign key (company_id, employee_id) references bokbuzz.employees(company_id, id),
  check (gross_ore = base_ore + bonus_ore),
  check (net_ore = gross_ore - tax_ore),
  check (tax_ore <= gross_ore)
);
create index payroll_lines_company_employee on bokbuzz.payroll_lines (company_id, employee_id);
create index payroll_runs_company_voucher on bokbuzz.payroll_runs (company_id, voucher_id);

-- Godkjente kjøringer er låst; linjer kan bare endres mens kjøringen er utkast.
create function bokbuzz.guard_payroll_run_update() returns trigger
language plpgsql
set search_path = pg_catalog, pg_temp as $$
begin
  if old.status <> 'draft' then
    raise exception 'Lønnskjøringen er låst' using errcode = 'P0001', hint = 'immutable';
  end if;
  if new.company_id <> old.company_id or new.year <> old.year or new.month <> old.month then
    raise exception 'Lønnskjøringens periode kan ikke endres' using errcode = 'P0001';
  end if;
  return new;
end $$;

create function bokbuzz.guard_payroll_line_change() returns trigger
language plpgsql
set search_path = pg_catalog, pg_temp as $$
declare
  st text;
begin
  select status into st from bokbuzz.payroll_runs where id = coalesce(new.run_id, old.run_id);
  if st is distinct from 'draft' then
    raise exception 'Lønnskjøringen er låst' using errcode = 'P0001', hint = 'immutable';
  end if;
  return coalesce(new, old);
end $$;

create trigger payroll_runs_guard before update on bokbuzz.payroll_runs
  for each row execute function bokbuzz.guard_payroll_run_update();
create trigger payroll_runs_no_delete before delete on bokbuzz.payroll_runs
  for each row execute function bokbuzz.reject_modification();
create trigger payroll_lines_guard before insert or update or delete on bokbuzz.payroll_lines
  for each row execute function bokbuzz.guard_payroll_line_change();

-- ---------------------------------------------------------------------------
-- Rettigheter og RLS
-- ---------------------------------------------------------------------------
grant select on bokbuzz.aga_rates to bokbuzz_app, bokbuzz_worker;
grant select on bokbuzz.payroll_settings, bokbuzz.employees, bokbuzz.payroll_runs, bokbuzz.payroll_lines
  to bokbuzz_app, bokbuzz_worker;
grant insert, update on bokbuzz.payroll_settings, bokbuzz.employees, bokbuzz.payroll_runs to bokbuzz_app;
grant insert, update, delete on bokbuzz.payroll_lines to bokbuzz_app;

do $$
declare t text;
begin
  foreach t in array array['payroll_settings', 'employees', 'payroll_runs', 'payroll_lines'] loop
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
