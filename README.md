# Bokbuzz – regnskapsplattform for taxi-ENK

Én Python-backend (FastAPI), én Postgres-database som eneste sannhetskilde, og KI som
bare lager forslag. Et menneske godkjenner alltid (minst to klikk) før noe bokføres.
Designet er beskrevet i redesign-dokumentet; denne koden er første fase av det.

## Struktur

```
backend/
  migrations/          SQL-migrasjoner (skjema, triggere, RLS, rettigheter, seed)
  src/bokbuzz/
    ledger/            hovedboken: post_voucher, MVA per linje, reversering, saldobalanse
    documents/         bilagsmottak: filtypekontroll, SHA-256, uforanderlig lagring
    ai/                leverandørnøytralt modellgrensesnitt (falsk modell + Gemini via Vertex AI EU)
    proposals/         uttrekk -> validering -> konteringsforslag (eskalering ved tvetydighet)
    review/            godkjenning i to klikk
    api/               HTTP-ruter, innlogging (Supabase JWT + krav om MFA), selskapstilgang
    jobs.py            jobbkø i Postgres (lease, ingen duplikater ved krasj)
    audit.py           revisjonslogg med hash-kjede (beregnes i databasen)
  tests/               pytest mot ekte Postgres
docs/
  OPPSETT.md           hva eier må sette opp (Supabase, Google Cloud, hemmeligheter)
  STATUS.md            hva som er bygget, og hva som gjenstår per fase
```

## Kjøre lokalt

Krever Python 3.12 og Postgres 16.

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
createdb bokbuzz_test
BOKBUZZ_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bokbuzz_test pytest -q

# API mot en lokal database
createdb bokbuzz
BOKBUZZ_MIGRATION_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bokbuzz python -m bokbuzz.migrate
cp .env.example .env
uvicorn bokbuzz.main:app --reload     # API på http://localhost:8000/docs
python -m bokbuzz.worker              # jobbarbeider (uttrekk og forslag)
```

Testene sletter og gjenoppretter skjemaet `bokbuzz` i testdatabasen. Pek dem aldri mot en ekte database.

## Viktige regler i koden

- Beløp er heltall i øre. Debet er positivt, kredit negativt.
- `ledger.service.post_voucher` er eneste vei inn i hovedboken. Databasen stopper i tillegg ubalanserte
  bilag, bokføring i lukket periode, endring/sletting av bokførte bilag og TRUNCATE – også for superbruker.
- KI-modellen har ingen verktøy og ingen skrivetilgang. Svaret valideres mot skjema, aritmetikk,
  tillatte kontoer og MVA-koder. Forslag lagres med modell, prompt-versjon, regelversjon og input-hash.
- Dokumenter kan bare bokføres via sitt forslag etter gjennomgang (klikk 1) og bekreftelse (klikk 2).
