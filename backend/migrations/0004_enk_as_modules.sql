-- 0004_enk_as_modules.sql
-- Bokbuzz for alle enkeltpersonforetak (ENK) og aksjeselskap (AS), ikke bare drosjer.
-- Kontoplanen settes sammen av en grunnmal per selskapsform og valgfrie bransjemoduler
-- (først «taxi»). Malen taxi_enk fra 0002 beholdes uendret for eksisterende selskaper.

alter table bokbuzz.companies
  add column org_form text not null default 'ENK' check (org_form in ('ENK', 'AS')),
  add column modules  text[] not null default '{}' check (modules <@ array['taxi']::text[]);

-- Grunnmal for begge selskapsformer (NS 4102). Kontoene som skiller ENK og AS ligger under.
create temporary table _base (number text, name text, account_type text, vat text) on commit drop;
insert into _base values
  ('1230', 'Personbiler',                                        'asset',     '1'),
  ('1250', 'Inventar, verktøy og maskiner',                      'asset',     '1'),
  ('1500', 'Kundefordringer',                                    'asset',     null),
  ('1900', 'Kontanter',                                          'asset',     null),
  ('1920', 'Bankinnskudd (næringskonto)',                        'asset',     null),
  ('2400', 'Leverandørgjeld',                                    'liability', null),
  ('2600', 'Forskuddstrekk',                                     'liability', null),
  ('2700', 'Utgående merverdiavgift',                            'liability', null),
  ('2710', 'Inngående merverdiavgift',                           'liability', null),
  ('2740', 'Oppgjørskonto merverdiavgift',                       'liability', null),
  ('2770', 'Skyldig arbeidsgiveravgift',                         'liability', null),
  ('2940', 'Skyldige feriepenger',                               'liability', null),
  ('3000', 'Salgsinntekt, avgiftspliktig',                       'income',    '3'),
  ('3020', 'Salgsinntekt, avgiftspliktig middels sats',          'income',    '31'),
  ('3100', 'Salgsinntekt, avgiftsfri',                           'income',    '5'),
  ('3200', 'Salgsinntekt, utenfor avgiftsområdet',               'income',    '6'),
  ('3600', 'Leieinntekter / andre driftsinntekter',              'income',    '3'),
  ('4000', 'Varekjøp',                                           'expense',   '1'),
  ('4300', 'Innkjøp av varer for videresalg, næringsmidler',     'expense',   '11'),
  ('5000', 'Lønn til ansatte',                                   'expense',   null),
  ('5180', 'Påløpte feriepenger',                                'expense',   null),
  ('5400', 'Arbeidsgiveravgift',                                 'expense',   null),
  ('6000', 'Avskrivning på driftsmidler',                        'expense',   null),
  ('6300', 'Leie lokale',                                        'expense',   '0'),
  ('6540', 'Inventar og småanskaffelser',                        'expense',   '1'),
  ('6700', 'Regnskaps- og revisjonshonorar',                     'expense',   '1'),
  ('6800', 'Kontorrekvisita',                                    'expense',   '1'),
  ('6860', 'Kurs og møter',                                      'expense',   '1'),
  ('6900', 'Telefon og mobilabonnement',                         'expense',   '1'),
  ('6940', 'Porto',                                              'expense',   '0'),
  ('7000', 'Drivstoff og lading',                                'expense',   '1'),
  ('7020', 'Vedlikehold og reparasjon bil',                      'expense',   '1'),
  ('7040', 'Forsikring og avgifter bil',                         'expense',   '0'),
  ('7090', 'Annen kostnad bil (vask, bompenger, parkering)',     'expense',   '1'),
  ('7140', 'Reisekostnad, ikke oppgavepliktig',                  'expense',   '13'),
  ('7320', 'Reklame og markedsføring',                           'expense',   '1'),
  ('7350', 'Representasjon, ikke fradragsberettiget',            'expense',   '0'),
  ('7500', 'Forsikringspremie',                                  'expense',   '0'),
  ('7770', 'Bank- og kortgebyrer',                               'expense',   '0'),
  ('7790', 'Annen driftskostnad',                                'expense',   '1'),
  ('8050', 'Renteinntekter',                                     'income',    '0'),
  ('8150', 'Rentekostnader',                                     'expense',   '0');

insert into bokbuzz.account_templates
  (template, number, name, account_type, saft_standard_account, default_vat_code)
select t.template, b.number, b.name, b.account_type, b.number, b.vat
  from _base b cross join (values ('enk'), ('as')) t(template);

insert into bokbuzz.account_templates
  (template, number, name, account_type, saft_standard_account, default_vat_code) values
  -- Enkeltpersonforetak: eier og foretak er samme skattesubjekt.
  ('enk', '2050', 'Egenkapital',                                  'equity',    '2050', null),
  ('enk', '2060', 'Privatuttak',                                  'equity',    '2060', null),
  ('enk', '2070', 'Privat innskudd (betalt med privat kort)',     'equity',    '2070', null),
  -- Aksjeselskap: eget skattesubjekt; utlegg fra eier er gjeld til aksjonær.
  ('as',  '2000', 'Aksjekapital',                                 'equity',    '2000', null),
  ('as',  '2050', 'Annen egenkapital',                            'equity',    '2050', null),
  ('as',  '2500', 'Betalbar skatt',                               'liability', '2500', null),
  ('as',  '2800', 'Avsatt utbytte',                               'liability', '2800', null),
  ('as',  '2910', 'Gjeld til aksjonær (utlegg betalt privat)',     'liability', '2910', null),
  ('as',  '1370', 'Fordring på aksjonær',                         'asset',     '1370', null),
  ('as',  '5330', 'Styrehonorar',                                 'expense',   '5330', null),
  ('as',  '8300', 'Betalbar skatt (kostnad)',                     'expense',   '8300', null),
  -- Valgfri modul: drosje.
  ('mod_taxi', '1570', 'Tilgode fra taxisentral (oppgjør)',         'asset',   '1570', null),
  ('mod_taxi', '3010', 'Kjøreinntekter, lav sats (persontransport)','income',  '3000', '33'),
  ('mod_taxi', '3110', 'Kjøreinntekter, avgiftsfri',                'income',  '3100', '5'),
  ('mod_taxi', '6790', 'Sentralavgift og provisjon taxisentral',    'expense', '6790', '1');

-- Ny inngang: grunnmal etter selskapsform pluss valgte moduler.
create function bokbuzz.create_company_v2(p_orgnr text, p_name text, p_org_form text,
                                          p_modules text[], p_vat_registered boolean)
returns uuid
language plpgsql security definer
set search_path = pg_catalog, pg_temp as $$
declare
  uid uuid := bokbuzz.current_user_id();
  cid uuid;
  base text := lower(p_org_form);
begin
  if uid is null then
    raise exception 'Ingen innlogget bruker' using errcode = '42501';
  end if;
  if p_org_form not in ('ENK', 'AS') then
    raise exception 'Bokbuzz støtter foreløpig bare ENK og AS, ikke %', p_org_form using errcode = '22023';
  end if;
  insert into bokbuzz.companies (orgnr, name, org_form, modules, vat_registered)
  values (p_orgnr, p_name, p_org_form, coalesce(p_modules, '{}'), coalesce(p_vat_registered, true))
  returning id into cid;
  insert into bokbuzz.company_members (company_id, user_id, role) values (cid, uid, 'owner');
  insert into bokbuzz.accounts (company_id, number, name, account_type, saft_standard_account,
                                grouping_code, default_vat_code)
  select distinct on (number) cid, number, name, account_type, saft_standard_account,
         grouping_code, default_vat_code
    from bokbuzz.account_templates
   where template = base
      or template = any (select 'mod_' || m from unnest(coalesce(p_modules, '{}')) m)
   order by number, (template = base) desc;
  insert into bokbuzz.audit_events (company_id, actor, event_type, entity_type, entity_id, payload)
  values (cid, uid, 'company.created', 'company', cid::text,
          jsonb_build_object('orgnr', p_orgnr, 'name', p_name, 'org_form', p_org_form,
                             'modules', to_jsonb(coalesce(p_modules, '{}')),
                             'vat_registered', coalesce(p_vat_registered, true)));
  perform bokbuzz.open_fiscal_year(cid, extract(year from (now() at time zone 'Europe/Oslo'))::integer);
  return cid;
end $$;

revoke all on function bokbuzz.create_company_v2(text, text, text, text[], boolean) from public;
grant execute on function bokbuzz.create_company_v2(text, text, text, text[], boolean) to bokbuzz_app;
