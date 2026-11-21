-- 0002_seed_vat_and_chart.sql
-- SAF-T standard MVA-koder og kontoplanmal for taxi-ENK (NS 4102).
--
-- VERIFISER: Kodene, satsene og datoene er lagt inn etter beste kunnskap og må
-- kontrolleres mot Skatteetatens liste over SAF-T standard MVA-koder og godkjennes
-- av regnskapsfører før første ekte bilag (port i fase 2).

insert into bokbuzz.vat_codes (code, description, direction, ledger_account) values
  ('0',  'Ingen MVA-behandling',                                   'none',   null),
  ('1',  'Fradrag for inngående MVA, alminnelig sats',             'input',  '2710'),
  ('11', 'Fradrag for inngående MVA, middels sats (næringsmidler)', 'input',  '2710'),
  ('13', 'Fradrag for inngående MVA, lav sats (persontransport)',  'input',  '2710'),
  ('3',  'Utgående MVA, alminnelig sats',                          'output', '2700'),
  ('31', 'Utgående MVA, middels sats',                             'output', '2700'),
  ('33', 'Utgående MVA, lav sats (persontransport)',               'output', '2700'),
  ('5',  'Innenlands omsetning fritatt for MVA (nullsats)',        'output', '2700'),
  ('6',  'Omsetning utenfor MVA-loven',                            'output', '2700');

insert into bokbuzz.vat_rates (code, rate_bp, valid_from, valid_to) values
  ('0',  0,    date '2000-01-01', null),
  ('1',  2500, date '2000-01-01', null),
  ('3',  2500, date '2000-01-01', null),
  ('11', 1500, date '2012-01-01', null),
  ('31', 1500, date '2012-01-01', null),
  -- Lav sats: 12 % fra 2018, midlertidig 6 % 1.4.2020–30.9.2021 (verifiser).
  ('13', 1200, date '2018-01-01', date '2020-03-31'),
  ('13', 600,  date '2020-04-01', date '2021-09-30'),
  ('13', 1200, date '2021-10-01', null),
  ('33', 1200, date '2018-01-01', date '2020-03-31'),
  ('33', 600,  date '2020-04-01', date '2021-09-30'),
  ('33', 1200, date '2021-10-01', null),
  ('5',  0,    date '2000-01-01', null),
  ('6',  0,    date '2000-01-01', null);

-- Kontoplanmal for taxi-ENK. saft_standard_account følger NS 4102-nummeret.
-- grouping_code (næringsspesifikasjonen) fylles inn i fase 2 sammen med regnskapsfører.
insert into bokbuzz.account_templates
  (template, number, name, account_type, saft_standard_account, default_vat_code) values
  ('taxi_enk', '1230', 'Personbiler (drosje)',                         'asset',     '1230', '1'),
  ('taxi_enk', '1500', 'Kundefordringer',                              'asset',     '1500', null),
  ('taxi_enk', '1570', 'Tilgode fra taxisentral (oppgjør)',             'asset',     '1570', null),
  ('taxi_enk', '1900', 'Kontanter',                                     'asset',     '1900', null),
  ('taxi_enk', '1920', 'Bankinnskudd (næringskonto)',                   'asset',     '1920', null),
  ('taxi_enk', '2050', 'Egenkapital',                                   'equity',    '2050', null),
  ('taxi_enk', '2060', 'Privatuttak',                                   'equity',    '2060', null),
  ('taxi_enk', '2070', 'Privat innskudd (betalt med privat kort)',      'equity',    '2070', null),
  ('taxi_enk', '2400', 'Leverandørgjeld',                               'liability', '2400', null),
  ('taxi_enk', '2600', 'Forskuddstrekk',                                'liability', '2600', null),
  ('taxi_enk', '2700', 'Utgående merverdiavgift',                       'liability', '2700', null),
  ('taxi_enk', '2710', 'Inngående merverdiavgift',                      'liability', '2710', null),
  ('taxi_enk', '2740', 'Oppgjørskonto merverdiavgift',                  'liability', '2740', null),
  ('taxi_enk', '3000', 'Kjøreinntekter, avgiftspliktig lav sats',       'income',    '3000', '33'),
  ('taxi_enk', '3100', 'Kjøreinntekter, avgiftsfri',                    'income',    '3100', '5'),
  ('taxi_enk', '3600', 'Leieinntekter / andre driftsinntekter',         'income',    '3600', '3'),
  ('taxi_enk', '6000', 'Avskrivning på driftsmidler',                   'expense',   '6000', null),
  ('taxi_enk', '6540', 'Inventar og småanskaffelser',                   'expense',   '6540', '1'),
  ('taxi_enk', '6790', 'Sentralavgift og provisjon taxisentral',        'expense',   '6790', '1'),
  ('taxi_enk', '6800', 'Kontorrekvisita',                               'expense',   '6800', '1'),
  ('taxi_enk', '6900', 'Telefon og mobilabonnement',                    'expense',   '6900', '1'),
  ('taxi_enk', '7000', 'Drivstoff og lading',                           'expense',   '7000', '1'),
  ('taxi_enk', '7020', 'Vedlikehold og reparasjon bil',                 'expense',   '7020', '1'),
  ('taxi_enk', '7040', 'Forsikring og avgifter bil',                    'expense',   '7040', '0'),
  ('taxi_enk', '7090', 'Annen kostnad bil (vask, bompenger, parkering)','expense',   '7090', '1'),
  ('taxi_enk', '7140', 'Reisekostnad, ikke oppgavepliktig',             'expense',   '7140', '13'),
  ('taxi_enk', '7350', 'Representasjon, ikke fradragsberettiget',       'expense',   '7350', '0'),
  ('taxi_enk', '7500', 'Forsikringspremie',                             'expense',   '7500', '0'),
  ('taxi_enk', '7770', 'Bank- og kortgebyrer',                          'expense',   '7770', '0'),
  ('taxi_enk', '7790', 'Annen driftskostnad',                           'expense',   '7790', '1'),
  ('taxi_enk', '8050', 'Renteinntekter',                                'income',    '8050', '0'),
  ('taxi_enk', '8150', 'Rentekostnader',                                'expense',   '8150', '0');
