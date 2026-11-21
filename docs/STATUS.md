# Status mot faseplanen

Oppdatert 21. november 2026. Første leveranse dekker kjernen fra fase 1–3 med testdata. Ingenting er
koblet til ekte kunder, skytjenester eller KI ennå.

## Bygget i denne runden

| Område | Hva | Akseptkriterium som er testet |
|---|---|---|
| Hovedbok | `post_voucher` i én transaksjon: idempotens, dokumentlås, rolle og godkjenning, åpen periode, aktive kontoer, MVA per linje, balanse, løpende nummer, revisjonshendelse | 100 samtidige bokføringer gir nummer 1–100 uten hull; samme idempotensnøkkel gir ett bilag; egenskapsbasert test (hundrevis av tilfeldige bilag) holder saldobalansen i null |
| Databasevern | Utsatt balansesjekk, låst linjeantall, triggere mot endring/sletting/TRUNCATE av bilag og logg, lukket periode kan ikke åpnes, ingen DELETE for app-rollene | Testet med direkte SQL, også som superbruker |
| Reversering | Nytt bilag i serie R med begrunnelse, bare én gang | Saldo går i null etter reversering |
| Tilgang | Supabase JWT, krav om MFA (`aal2`), roller per selskap, RLS i databasen | Automatisk test går gjennom **alle** selskapsruter og viser 404 for fremmed bruker |
| Revisjonslogg | Hash-kjede per selskap, beregnet i databasen | Endret eller slettet rad oppdages |
| Bilag inn | Filtype fra innhold, størrelsesgrense, SHA-256, innholdsadressert lagring (lokal / Cloud Storage), jobb i samme transaksjon | Samme fil to ganger gir ett dokument |
| Jobbkø | Postgres, `SKIP LOCKED`, lease og nye forsøk | Jobb som krasjer før commit fullføres etter omstart uten duplikater |
| KI-forslag | Leverandørnøytralt grensesnitt, falsk modell i tester, Gemini via Vertex AI EU klar i kode | Aritmetikk, MVA, kontotype og retning valideres; eskalering bare ved tvetydighet/feil, ikke ved manglende felt; dokument med skjulte instrukser gir bare et forslag |
| Godkjenning | To klikk: åpne (personlig engangs-token) og bekrefte; rettelser tillatt; regelendring gjør forslag ugyldig | Ett-klikk avvises; token kan ikke brukes av andre eller to ganger; dokument kan ikke bokføres utenom sitt forslag |
| Drift | Dockerfile, GitHub Actions (lint, tester mot Postgres 16, container-bygg) | |

## Gjenstår (neste runder)

- **Fase 0 (eier):** rotere lekket legitimasjon, deaktivere n8n-webhooken, regnskapsfører starter
  autorisasjonssøknad. Avstemmingsmodulen (`reconcile.py`, 22 tester) må legges inn når arkivet er tilgjengelig;
  den finnes ikke i repoet ennå.
- **Fase 1:** virusskanning og isolert parsing av filer, invitasjon av brukere og rolleadministrasjon,
  Brønnøysund-oppslag, daglig forankring av hash-kjeden i låst lagring, restore-øvelse.
- **Fase 2:** åpningsbalanse, grupperingskoder for næringsspesifikasjonen, regnskapsførers godkjenning av
  kontoplan og MVA-koder, flere bilagsserier.
- **Fase 3:** mobil-PWA (React) for opplasting og godkjenningskø, leverandørregler før KI, gullstandard-sett
  (200 bilag), kostnadstak per selskap, utenlandsk valuta og kreditnotaer i forslag.
- **Fase 4–6:** CAMT.053, taxioppgjør og avstemming, MVA-melding, SAF-T, pliktige spesifikasjoner.

## Bevisste valg som bør vurderes

- MVA-avvik på inntil 1 øre per linje godtas når bilaget oppgir MVA-beløpet (avrunding på kvitteringen).
- Betalt med privat kort føres mot 2070 «Privat innskudd». Regnskapsfører bør bekrefte kontoen.
- Et forslag som mangler dato e.l. går til «needs_manual» og kan bare godkjennes med en rettet kontering.
