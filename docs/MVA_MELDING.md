# MVA-meldingen: hva som er klart, og hva som mangler

Oppdatert 24. november 2026.

## Klart i Bokbuzz

- **Beregning per termin** fra hovedboken (`GET /companies/{id}/vat-returns/{år}/{termin}`): grunnlag og
  MVA per kode, sum å betale eller til gode, frist.
- **Kontroller før innsending** (MVA-agenten, regelstyrt): bilag som venter på kontroll (stopper innsending),
  banklinjer som ikke er avstemt, kontoutskrift som ikke dekker hele terminen, måneder som ikke er lukket.
- **XML-utkast** etter Skatteetatens format `mvaMeldingDto` (`.../xml`), som kunden kan laste ned.
- **Skjermen «MVA-melding»** i appen (via Saldo). Knappen «Send til Skatteetaten» er av til tilgangen er på plass.
- **Grensesnitt for innsending** (`bokbuzz/vat/submission.py`) med validering og innsending som egne steg.
  Til tilgangen er på plass svarer det med en tydelig melding (HTTP 503).

## Hvordan innsending skal virke

Skatteetaten skriver at MVA-meldingen også i 2026 sendes med **innlogging i ID-porten**:

1. Kunden trykker «Send til Skatteetaten» og logger inn med ID-porten (BankID).
2. Bokbuzz får et token på kundens vegne og sender XML-en til Skatteetatens **validerings-API**. Feil vises i appen.
3. Kunden ser oppsummeringen og bekrefter (eget klikk).
4. Bokbuzz oppretter innsendingen via Altinn, laster opp meldingen og fullfører. Kvitteringen lagres i
   revisjonsloggen.

Bokbuzz sender aldri uten at kunden selv har bekreftet.

## Det eier må skaffe (samme bedrift og org.nr. som eier Bokbuzz)

| Hva | Hvor | Merknad |
|---|---|---|
| Tilgang til Samarbeidsportalen og godkjente bruksvilkår for ID-porten og Maskinporten | samarbeid.digdir.no | Daglig leder logger inn med BankID |
| ID-porten-integrasjon (først testmiljø) | Samarbeidsportalen | Redirect-adressen til appen |
| Tilgang til Skatteetatens API for MVA-meldingen (validering og innsending) | skatteetaten.no/samarbeidspartnere/sluttbrukersystemer | Scopes oppgis av Skatteetaten |
| Virksomhetssertifikat (Buypass eller Commfides) | Leverandøren | Trengs for Maskinporten og systembruker senere |
| Testbrukere og testselskaper | Tenor (Skatteetaten) | For testmiljøet |

## Må verifiseres i testmiljøet før første ekte innsending

Merket `VERIFISER` i `backend/src/bokbuzz/vat/return_draft.py`:

- fortegn på fradragslinjer (Bokbuzz sender inngående MVA som negativt beløp),
- om grunnlag skal oppgis for fradragskoder (Bokbuzz sender det bare for utgående koder),
- avrunding (Bokbuzz sender kroner med to desimaler),
- elementnavn og verdi for årstermin,
- frister per termin.

Kilder: [Skatteetaten om Altinn 3 og MVA](https://www.skatteetaten.no/en/our-partners/end-user-systems/sbs-nyheter/informasjon-om-overgangen-fra-altinn-2-til-altinn-3-for-de-moderniserte-losningene-skattemelding-og-mva/),
[MVA-meldingen for utviklere](https://skatteetaten.github.io/mva-meldingen/),
[Systembruker](https://skatteetaten.github.io/api-dokumentasjon/en/om/systembruker).
