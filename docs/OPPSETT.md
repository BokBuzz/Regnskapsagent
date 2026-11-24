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

Alt i Google Cloud beskrives som kode i `infra/terraform`. Du oppretter prosjektet og fakturering selv,
og kjører Terraform fra din egen maskin (eller Cloud Shell). Claude har ikke opprettet noe.

### 2.1 Engangsoppsett i konsollen (ca. 15 min)

1. Gå til <https://console.cloud.google.com/projectcreate> og lag prosjektet, f.eks. `bokbuzz-prod`.
   Koble det til en faktureringskonto.
2. Sett et **budsjettvarsel** under *Billing → Budgets & alerts*, f.eks. 30 USD/mnd med varsel ved 50/90/100 %.
3. Godta **Cloud Data Processing Addendum** under *IAM & Admin → Settings / Privacy & Security*.
4. Åpne **Cloud Shell** (ikonet `>_` øverst til høyre). Den har `gcloud` og `terraform` ferdig installert.

### 2.2 Terraform (ca. 10 min)

Kjør i Cloud Shell, bytt ut `bokbuzz-prod` med ditt prosjekt:

```bash
export PROJECT=bokbuzz-prod
gcloud config set project $PROJECT

# Bøtte for Terraform-tilstand (én gang)
gcloud storage buckets create gs://$PROJECT-tfstate --location=europe-west4 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$PROJECT-tfstate --versioning

git clone https://github.com/BokBuzz/Regnskapsagent.git && cd Regnskapsagent/infra/terraform
cp terraform.tfvars.example terraform.tfvars   # rediger project_id og documents_bucket_name
terraform init -backend-config="bucket=$PROJECT-tfstate"
terraform plan      # les gjennom
terraform apply
```

Dette lager: API-er, Artifact Registry, bøtta for originalbilag (versjonert, ikke offentlig, med
oppbevaringsregel som **ikke** er låst ennå), tre tjenestekontoer med minste rettigheter, to
hemmeligheter uten verdi, Cloud Run-tjenestene `bokbuzz-api` og `bokbuzz-worker` (med et
plassholderbilde), og nøkkelfri innlogging for GitHub Actions begrenset til `main`.

### 2.3 Hemmeligheter (database-URL-er)

Lag først innloggingsrollene i Supabase (punkt 1.4), og legg så inn URL-ene **uten å lime dem i chat**:

```bash
# Session pooler, port 5432. Brukernavn har formen <rolle>.ihmjkupqpgixmnguixds
printf '%s' 'postgresql://bokbuzz_api.ihmjkupqpgixmnguixds:<passord>@<pooler-host>:5432/postgres?sslmode=require' \
  | gcloud secrets versions add bokbuzz-api-database-url --data-file=-
printf '%s' 'postgresql://bokbuzz_jobs.ihmjkupqpgixmnguixds:<passord>@<pooler-host>:5432/postgres?sslmode=require' \
  | gcloud secrets versions add bokbuzz-worker-database-url --data-file=-
```

Pooler-host finner du i Supabase under *Connect → Session pooler*.

### 2.4 Sjekk at KI-modellene virker på EU-endepunktet

```bash
cd ~/Regnskapsagent/backend && pip install -e '.[gcp]'
gcloud auth application-default login
BOKBUZZ_AI_PROVIDER=vertex BOKBUZZ_GCP_PROJECT=$PROJECT python -m bokbuzz.ai.smoke
```

Kommandoen sender en oppdiktet kvittering (ingen kundedata) til begge modellene og viser svar, tokenbruk og
kostnad. Får du «model not found», finn riktige modell-ID-er i Vertex AI Model Garden og sett
`model_default` / `model_escalation` i `terraform.tfvars` og `BOKBUZZ_MODEL_DEFAULT` /
`BOKBUZZ_MODEL_ESCALATION` lokalt, og oppdater `model_prices` i `backend/src/bokbuzz/config.py`.

### 2.5 Koble GitHub til deploy

1. Kjør `terraform output` og noter `artifact_repository`, `workload_identity_provider` og
   `deployer_service_account`.
2. I GitHub: *Settings → Environments → New environment* `production` (gjerne med deg selv som
   påkrevd godkjenner).
3. *Settings → Secrets and variables → Actions → Variables*, legg inn:
   `GCP_PROJECT_ID`, `GCP_REGION` (`europe-west4`), `GCP_ARTIFACT_REPO`, `GCP_WIF_PROVIDER`, `GCP_DEPLOYER_SA`.
4. Kjør workflowen **Deploy** manuelt (*Actions → Deploy → Run workflow*). Den bygger bildet, ruller ut
   API og arbeider, og sjekker `/health`. Etter det deployes hver merge til `main` automatisk.

### 2.6 Senere

- **Lås oppbevaringen** først når regnskapsfører har bekreftet fristen: sett `lock_documents_retention = true`
  og kjør `terraform apply`. Det kan aldri angres, og bøtta kan da ikke slettes før fristen er ute.
- Nye databasemigrasjoner kjøres manuelt mot Supabase **før** PR-en som trenger dem merges.

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
