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

## Runde 2 (21.11.2026): sky og KI

| Område | Hva | Testet |
|---|---|---|
| Vertex AI | Gemini via `eu`-endepunktet med tjenestekonto (aldri API-nøkkel), tidsavbrudd og nye forsøk ved 429/5xx, tenke-tokens telles som output | Adapteren testes uten nettverk; `python -m bokbuzz.ai.smoke` sjekker ekte modeller når GCP er satt opp |
| Kostnadstak | Pris per modell i konfigurasjon, kostnad lagres per forslag, tak per selskap og måned (standard 5 USD) | Over taket konteres bilag manuelt, og eskalering stoppes |
| Produksjonsvern | Prod nekter falsk modell, lokal lagring og modeller uten pris | Testet |
| Infrastruktur som kode | `infra/terraform`: API-er, Artifact Registry, låsbar bøtte, tjenestekontoer, hemmeligheter, Cloud Run API + arbeider, nøkkelfri GitHub-deploy | `terraform validate` |
| Deploy | `.github/workflows/deploy.yml`: bygg, push og utrulling ved merge til main, når repo-variablene er satt | Kjøres først når eier har satt opp GCP |

## Runde 3 (23.11.2026): kundeapp, alle ENK og AS

| Område | Hva | Testet |
|---|---|---|
| Kundeapp (PWA) | `frontend/`: innlogging med MFA, oppstart med Brønnøysund-oppslag, opplasting med kamera, kontroll og bokføring i to klikk, avvisning, bokførte bilag med reversering, saldobalanse | vitest, `tsc`, bygg i CI; hele flyten kjørt i nettleser mot lokal backend |
| Selvbetjening | `/me`, `/vat-codes`, `/lookup/orgnr/{orgnr}`, forslagsdetaljer, CORS | 6 tester |
| ENK og AS | Migrasjon 0004: grunnmal `enk` og `as` (NS 4102), valgfri modul `mod_taxi`, `companies.org_form` og `modules`, `create_company_v2`. «Betalt privat» går til 2070 i ENK og 2910 «Gjeld til aksjonær» i AS. Instruksen til KI nevner selskapsform og bransje | 5 tester |

**Migrasjon 0004 må kjøres i Supabase før denne koden tas i bruk** (`python -m bokbuzz.migrate`).

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
- Betalt med privat kort føres mot 2070 «Privat innskudd» i ENK og 2910 «Gjeld til aksjonær» i AS.
  Regnskapsfører bør bekrefte kontoene.
- Andre selskapsformer (NUF, DA, ANS, SA) avvises foreløpig ved oppstart.

## Ekstra krav for aksjeselskap (planlagt)

| Krav | Frist / merknad | Plan i Bokbuzz |
|---|---|---|
| Årsregnskap med noter til Regnskapsregisteret | Innen 31. juli; små foretak kan bruke forenklede regler | Fase 6: resultat, balanse og noteutkast fra hovedboken; kunden kontrollerer og sender inn |
| Skattemelding for AS (med næringsspesifikasjon) | 31. mai | Fase 6: grupperingskoder per konto, utkast til næringsspesifikasjon |
| Aksjonærregisteroppgaven (RF-1086) | 31. januar | Enkel registrering av aksjonærer, utbytte og kapitalendringer; utkast til oppgave |
| A-melding | Den 5. hver måned når det er ansatte eller styrehonorar | Ikke lønnssystem i første versjon; kontoene 5000–5400 finnes, lønn føres fra lønnssystemets bilag |
| Revisjon | Plikt over terskelverdiene (omsetning, balanse, ansatte); ellers kan generalforsamlingen velge den bort | Spørsmål ved oppstart; lesetilgang for revisor senere |
| Egenkapital og utbytte | Forsvarlig egenkapital, utbytte vedtas av generalforsamlingen og føres mot 2800 | Kontoer finnes; vedtak og varsel om lav egenkapital senere |
| Lån til aksjonær | Kan beskattes som utbytte | Varsel når 1370 får saldo |

Fristene og tersklene må bekreftes av regnskapsfører før de vises til kunder.
- Et forslag som mangler dato e.l. går til «needs_manual» og kan bare godkjennes med en rettet kontering.
