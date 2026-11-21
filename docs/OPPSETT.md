# Oppsett eier må gjøre selv

Ingenting her er opprettet av Claude. Kontoer, nøkler og betalte tjenester må du sette opp selv.
Rekkefølgen under er anbefalt.

## 1. Supabase (database og innlogging)

**Status 21.11.2026:** Prosjektet `bokbuzz` (ref `ihmjkupqpgixmnguixds`, region `eu-west-1` Irland, Postgres 17)
er opprettet. Migrasjonene `0001`–`0003` er kjørt via Supabase-connectoren og registrert i
`bokbuzz_meta.schema_migrations` med samme sjekksum som filene, så `python -m bokbuzz.migrate` hopper over dem
og kjører bare nye filer. Sikkerhetsrådene (advisors) er tomme etter `0003`. API-URL:
`https://ihmjkupqpgixmnguixds.supabase.co`.

Det som gjenstår må du gjøre selv i dashboardet:

1. **Plan og konto**: oppgrader organisasjonen til **Pro** før ekte data, og slå på tofaktor for din egen
   Supabase-konto (*Account → Security*).
2. **Databasepassord**: hvis passordet til `postgres` har vært vist eller delt noe sted, lag et nytt under
   *Project Settings → Database*. Lagre det bare i en passordbehandler.
3. **Authentication → Multi-Factor**: slå på TOTP. API-et avviser innlogging uten MFA (`aal2`).
4. **Innloggingsroller** for API og arbeider. Kjør i SQL-editoren (rollene `bokbuzz_app` og
   `bokbuzz_worker` finnes allerede). Bruk lange, tilfeldige passord, og ikke lim dem inn i chat:
   ```sql
   create role bokbuzz_api login password '<lang tilfeldig>' in role bokbuzz_app;
   create role bokbuzz_jobs login password '<lang tilfeldig>' in role bokbuzz_worker;
   ```
5. API og arbeider må koble til via **Session pooler** (port 5432) eller direkte, ikke Transaction pooler
   (port 6543). Koden setter databaserolle per tilkobling, og det tåler ikke transaksjonsmodus.
   Med pooleren blir brukernavnet `bokbuzz_api.ihmjkupqpgixmnguixds`.
6. Ikke legg skjemaet `bokbuzz` til i *API → Exposed schemas*. Migrasjonen tar uansett bort tilgang for
   `anon` og `authenticated` (kontrollert: ingen av dem har tilgang til `bokbuzz` eller `bokbuzz_meta`).
7. **DPA**: signer Supabase sin databehandleravtale (*Organization → Legal Documents*).
8. Slå på Point-in-Time Recovery (tillegg på Pro) når piloten nærmer seg.

Nye migrasjoner senere kjøres med eierrollen (`postgres`), via Session pooler eller direkte tilkobling:
```bash
BOKBUZZ_MIGRATION_DATABASE_URL='postgresql://postgres:<pw>@<host>:5432/postgres' python -m bokbuzz.migrate
```

## 2. Google Cloud (API, arbeider, lagring, KI)

1. Opprett et prosjekt kun for Bokbuzz, med fakturering.
2. Slå på API-ene: Cloud Run, Artifact Registry, Cloud Storage, Secret Manager, Vertex AI.
3. **Lagring av originalbilag**: opprett en bøtte i EU (f.eks. `europe-west4`), med
   *uniform bucket-level access*, versjonering, og en oppbevaringsregel på minst 5 år + inneværende år.
   Lås regelen (Bucket Lock) først når regnskapsfører har bekreftet fristen – låsen kan ikke angres.
4. **Tjenestekontoer**: én for API og én for arbeider. API trenger `Storage Object Creator` +
   `Storage Object Viewer` på bøtta. Arbeideren trenger `Storage Object Viewer` og `Vertex AI User`.
   Ingen av dem skal ha slette-rettigheter i bøtta.
5. **Secret Manager**: legg inn `BOKBUZZ_DATABASE_URL` (én per tjeneste, med riktig rolle) og eventuelt
   `BOKBUZZ_SUPABASE_JWT_SECRET` hvis du ikke bruker JWKS.
6. **Cloud Run** (`europe-west4`): to tjenester fra samme bilde (`backend/Dockerfile`):
   - API: standardkommando. Miljø: `BOKBUZZ_ENVIRONMENT=prod`, `BOKBUZZ_SUPABASE_URL=https://ihmjkupqpgixmnguixds.supabase.co`,
     `BOKBUZZ_STORAGE_BACKEND=gcs`, `BOKBUZZ_GCS_BUCKET=<bøtte>`.
   - Arbeider: kommando `python -m bokbuzz.worker`, minst én instans, CPU alltid tildelt. I tillegg
     `BOKBUZZ_AI_PROVIDER=vertex`, `BOKBUZZ_GCP_PROJECT=<prosjekt>`, `BOKBUZZ_VERTEX_LOCATION=eu`.
7. Godta Googles databehandleravtale (Cloud Data Processing Addendum) i konsollen.

## 3. Ting som må verifiseres før første ekte bilag

- Eksakte modell-ID-er i Vertex AI for standard- og eskaleringsmodellen (`BOKBUZZ_MODEL_DEFAULT`,
  `BOKBUZZ_MODEL_ESCALATION`), og at de er tilgjengelige på EU-endepunktet.
- MVA-koder, satser og datoer i `backend/migrations/0002_seed_vat_and_chart.sql` mot Skatteetatens liste
  over SAF-T standard MVA-koder.
- Kontoplanmalen for taxi-ENK (særlig egenkapital- og privatkontoer) og koblingen til næringsspesifikasjonen,
  godkjent av regnskapsfører.
- Oppbevaringsfrister før Bucket Lock låses.

## 4. Ikke gjør

- Ikke bruk AI Studio-nøkler (`GEMINI_API_KEY`) med kundedata.
- Ikke bruk Supabase sin `service_role`-nøkkel eller `postgres`-brukeren i API eller arbeider.
- Ikke kjør testene mot en ekte database; de sletter skjemaet.
