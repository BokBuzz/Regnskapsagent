# Lønn i Bokbuzz: plan og arkitektur

Oppdatert 24. november 2026. Eier har bestemt at Bokbuzz skal ha **egen lønnskjøring**, ikke integrasjon
mot et annet lønnssystem. Dette dokumentet beskriver flyten, hva som må på plass hos myndigheter og bank,
og i hvilken rekkefølge vi bygger. Frister, satser og API-detaljer må verifiseres mot Skatteetaten og NAV
før de brukes med ekte kunder.

## Flyten kunden ser

```
 1. Kjør lønn          Kunden velger måned, ser utkast per ansatt (brutto, trekk, netto, feriepenger)
        │               og godkjenner (to klikk). Lønnsbilaget bokføres.
        ▼
 2. Send A-melding     Bokbuzz lager A-meldingen. Kunden bekrefter, og Bokbuzz sender den til
        │               Skatteetaten på kundens vegne (systembruker via Maskinporten).
        ▼
 3. Tilbakemelding     Bokbuzz henter tilbakemeldingen: avvik, beregnet forskuddstrekk og
        │               arbeidsgiveravgift. Avvik vises i klartekst med forslag til retting.
        ▼
 4. Betalinger         Bokbuzz lager betalingene: nettolønn til hver ansatt, skattetrekk og
        │               arbeidsgiveravgift til Skatteetaten med riktig KID og forfall.
        ▼
 5. Nettbank           Betalingene sendes til banken, og kunden godkjenner dem i nettbanken med BankID.
        │               Bokbuzz flytter aldri penger på egen hånd.
        ▼
 6. Avstemming         Når kontoutskriften kommer, kobles betalingene automatisk mot lønnsbilaget
                        (bankagenten fra PR #4).
```

Kunden har ansvaret og bekrefter hvert steg som sender noe ut (A-melding og betalinger). Det følger
prinsippet i roadmapen: agenter lager utkast, kunden forplikter.

## Det lønnsmotoren må kunne (første versjon)

| Område | Første versjon | Senere |
|---|---|---|
| Ansatte | Fødselsnummer, stilling, stillingsprosent, arbeidsforhold, bankkonto, startdato | Ansattportal, lønnsslipp i app |
| Lønnsarter | Fastlønn, timelønn, overtid, bonus, styrehonorar (AS) | Naturalytelser, fri bil, telefon |
| Skattetrekk | Hentes fra **skattekortet** (tabell eller prosent) via Skatteetatens API for skattekort til arbeidsgiver | Frikort, kildeskatt for utenlandske |
| Feriepenger | Opptjening hvert år (10,2 % / 12 % ved 5 uker), utbetaling i juni, ferietrekk | Femte ferieuke, over 60 år |
| Arbeidsgiveravgift | Sats etter sone for kommunen | Fribeløp i sone 1a, særregler |
| Pensjon (OTP) | Minst 2 % trekk og kostnad for den som er pliktig | Integrasjon mot pensjonsleverandør |
| Lønnsslipp | PDF til ansatt | I ansattportal |
| Bokføring | Lønnsbilag med 5000, 5180, 5400, 2600, 2770, 2940 osv. | Avdeling og prosjekt |
| Sykepenger og foreldrepenger | Ikke i første versjon (vises som begrensning) | Refusjon fra NAV, inntektsmelding |
| Reiseregning og utlegg | Ikke i første versjon | Egen modul |

## Myndigheter: hva som kreves

| Integrasjon | Hva | Status / ledetid |
|---|---|---|
| **Maskinporten-klient** | Samme klient som for MVA senere. Krever avtale med Digdir og virksomhetssertifikat. | Eier søker nå |
| **Systembruker i Altinn 3** | Bokbuzz registreres i Altinns systemregister. Hver kunde godkjenner Bokbuzz som systembruker i Altinn én gang (ved oppstart i appen). | Etter Maskinporten |
| **A-melding** | Skatteetaten har tatt i bruk et nytt API for A-meldingen med Maskinporten og systembruker. Bokbuzz må be om tilgang (scope) og teste i testmiljøet med Tenor-data. | Uker, etter Maskinporten |
| **Tilbakemelding på A-melding** | Hentes fra samme API eller som melding i Altinn (Dialogporten). | Sammen med A-melding |
| **Skattekort** | Eget API hos Skatteetaten for skattekort til arbeidsgiver. Egen tilgang. | Sammen med A-melding |
| **KID for skattetrekk og arbeidsgiveravgift** | Skatteetaten tildeler KID per virksomhet og kravtype. Kunden legger dem inn ved oppstart (eller vi henter dem hvis API finnes). | Ingen søknad |

Detaljene (scopes, tilgangspakker, meldingsformat) hentes fra Skatteetatens dokumentasjon når vi starter.

## Bank: hvordan betalingene kommer til nettbanken

| Løsning | Hva kunden gjør | Krav | Anbefaling |
|---|---|---|---|
| **A. Betalingsfil (pain.001)** | Laster ned fil fra Bokbuzz og laster den opp i nettbanken, godkjenner med BankID | Banken må tilby filopplasting (vanlig i bedriftsnettbank, ikke alltid for små bedrifter) | **Første versjon.** Ingen avtale for Bokbuzz |
| **B. Betalingsinitiering via PSD2** | Trykker «Send til banken» i Bokbuzz, godkjenner i bankens app | Avtale med lisensiert aggregator med betalingsinitiering (eller egen lisens fra Finanstilsynet) | Versjon 2, sammen med bankkobling (PSD2) |
| **C. Direkte bankintegrasjon** | Som B | Egen avtale med hver bank | Bare hvis en bank krever det |

**Skattetrekkskonto:** arbeidsgiver skal ha trekkene på en egen skattetrekkskonto (eller bankgaranti).
Bokbuzz minner om dette ved oppstart av lønn og lager overføringen til skattetrekkskontoen sammen med
lønnskjøringen.

## Hvem gjør hva i arkitekturen

- **Lønnsmotor (regelkode, ikke KI):** beregner brutto, trekk, feriepenger og avgift. Testes med faste
  eksempler fra Skatteetatens trekktabeller.
- **Lønnsagent (KI):** forklarer lønnsslippen og avvik i tilbakemeldingen på enkel norsk, minner om frister
  og manglende opplysninger. Har bare lese- og utkasttilgang.
- **Kunden:** godkjenner lønnskjøringen, sender A-meldingen og godkjenner betalingene i nettbanken.

## Rekkefølge og tid

| Steg | Innhold | Avhenger av | Anslag |
|---|---|---|---|
| L0 | Ansattregister, lønnskjøring, lønnsbilag, lønnsslipp, betalingsfil (pain.001) med KID | Ingenting | 4–6 uker |
| L1 | A-melding og tilbakemelding via API | Maskinporten, systembruker, A-meldings-tilgang | 4–6 uker etter tilgang |
| L2 | Skattekort automatisk, feriepenger og ferietrekk fullt ut | Tilgang til skattekort-API | 3–4 uker |
| L3 | «Send til banken» via PSD2-betalingsinitiering | Aggregatoravtale | 3–4 uker |
| L4 | Sykepenger, NAV-refusjon, OTP-integrasjon, ansattportal | | Senere |

Til L1 er på plass kan kunden sende A-meldingen selv i Altinn med tallene fra Bokbuzz. Lønn kommer etter
pilot-MVP (bank, faktura, MVA), men L0 kan bygges mens tilgangene behandles.

## Risiko

- Lønn er det mest regelstyrte området i regnskap. Feil i trekk eller A-melding rammer ansatte direkte.
  Derfor regelkode med faste testeksempler, og partner-regnskapsfører bør gå gjennom første versjon.
- Hver ny regel (satser, soner, frikort) endres årlig. Satsene lagres med gyldighetsdato, som MVA-satsene.
