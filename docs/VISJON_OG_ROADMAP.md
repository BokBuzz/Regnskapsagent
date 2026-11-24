# Bokbuzz: visjon, produktkart og arkitektur

Oppdatert 24. november 2026. Dette dokumentet er et kart, ikke en bestilling. Det sier hva vi skal bygge,
i hvilken rekkefølge, og hva som krever avtaler eller godkjenning fra andre før vi kan bygge det.

## 1. Visjonen i én setning

Fiken er regnskapsprogram der kunden fører regnskapet. Bokbuzz skal være en **KI-drevet økonomiavdeling**:
programmet gjør nesten alt arbeidet, forklarer hvorfor, og kunden kontrollerer og godkjenner.

Det som ikke endres:

- **Kunden har ansvaret for regnskapet.** Bokbuzz er selvbetjent programvare, ikke regnskapsføring for andre.
  Vi trenger derfor ikke autorisasjon fra Finanstilsynet for programmet (bekreftes med advokat før lansering).
  Selger vi senere «vi fører for deg», krever det autorisert regnskapsførerselskap.
- **KI lager forslag, mennesket bokfører.** Alt som endrer hovedboken, sender noe ut av huset eller flytter
  penger, krever en logget godkjenning fra en bruker med rett rolle.
- **Hovedboken har én vei inn** (`post_voucher`), og databasen stopper ubalanse, endring av bokførte bilag og
  bokføring i lukket periode.

### Hva «95 % autonomi» betyr hos oss

95 % autonomi betyr **ikke** at KI bokfører 95 % alene. Det betyr at for 95 % av bilagene er forslaget
riktig nok til at kunden godkjenner uten å endre noe. Vi måler det slik:

| Mål | Definisjon | Mål for pilot | Mål ved paritet |
|---|---|---|---|
| Treffrate | Andel forslag godkjent uten endring av konto, MVA, beløp eller dato | 80 % | 95 % |
| Tid per bilag | Fra opplasting til bokført, kundens aktive tid | < 20 sek | < 8 sek |
| Feil etter bokføring | Andel bilag som reverseres innen 90 dager | < 2 % | < 0,5 % |

Godkjenning skjer fortsatt i minst to klikk per bilag. Vi kan gjøre godkjenning raskere (gruppere like
bilag, vise bare det som er usikkert), men vi lager ikke «godkjenn alt med ett klikk».

## 2. Hvor ærlige vi må være

Fiken har over ti år og et stort team bak seg. Bokbuzz har én utvikler. Det betyr:

1. **Vi vinner ikke på bredde først.** Vi vinner på at de vanligste jobbene (bilag, bank, faktura, MVA)
   går mye raskere enn i Fiken. Bredden kommer etter piloten.
2. **Vi kjøper der andre har sertifisering.** PEPPOL-aksesspunkt, bankdata (PSD2) og lønn bygger vi ikke
   selv i første omgang. Vi integrerer mot leverandører som allerede har godkjenningene.
3. **Regelstyrt der det går, KI der det trengs.** Bankavstemming, MVA-beregning og frister er regler.
   KI brukes til å lese dokumenter, foreslå kontering, forklare og svare på spørsmål.
4. **Noen Fiken-funksjoner kommer sent eller aldri** for målgruppen ENK og små AS: lager, innkjøpsordrer og
   mange kasseintegrasjoner. Vi lager arkitekturen åpen, men bygger dem når kundene ber om det.

## 3. Fiken-funksjoner mot Bokbuzz i dag

Tegn: ✅ finnes på `main` · 🟡 i PR #3 (ikke merget) · ⬜ ikke startet.
Fase viser når det kommer (se kapittel 4).

### Regnskap og bokføring

| Funksjon | I dag | Fase | Merknad |
|---|---|---|---|
| Standard kontoplan (NS 4102) | ✅ / 🟡 | – | Grunnmal i 0002; egne maler for ENK og AS i 0004 |
| Dobbelt bokholderi | ✅ | – | Balanse sjekkes i kode og i databasen |
| Automatiske konteringsforslag | ✅ | – | Gemini via Vertex AI EU, validert mot regler |
| MVA-håndtering per linje | ✅ | – | MVA-koder og satser med gyldighetsdato |
| MVA-melding og innsending | ⬜ | 1 | Skatteetatens API for MVA-melding, se kap. 6 |
| Revisjonsspor | ✅ | – | Hash-kjede per selskap, uforanderlige bilag |
| Hovedbok og saldobalanse | ✅ / 🟡 | – | Rapportside i PR #3 |
| SAF-T Regnskap (eksport) | ⬜ | 1 | Lovpålagt ved forespørsel; trengs også for å bytte system |
| Kunde- og leverandørreskontro | ⬜ | 2 | Krever kunde- og leverandørregister og åpne poster |
| Prosjekt- og avdelingsregnskap | ⬜ | 2 | Dimensjoner på bilagslinjer; enkelt å legge inn tidlig i skjema |
| Budsjett | ⬜ | 3 | KI kan foreslå budsjett fra fjoråret |
| Resultat og balanse | ⬜ | 2 | Fra saldobalansen med standard oppstilling |
| Kontantstrøm | ⬜ | 3 | Indirekte metode fra balanseendringer |
| Årsoppgjør ENK (næringsspesifikasjon) | ⬜ | 2 | Grupperingskoder per konto; kunden sender selv |
| Årsregnskap AS og skattemelding AS | ⬜ | 3 | Regnskapsregisteret og Skatteetaten; noteutkast |

### Fakturering

| Funksjon | I dag | Fase | Merknad |
|---|---|---|---|
| Lage faktura (PDF, e-post, KID) | ⬜ | 1 | Minste versjon i pilot: faktura, PDF, e-post, bokføring |
| Kreditnota | ⬜ | 1 | Følger med faktura |
| Tilbud og tilbud til faktura | ⬜ | 2 | |
| Repeterende faktura | ⬜ | 2 | |
| Automatisk purring og rentenota | ⬜ | 2 | Inkassoloven: purregebyr og varsel følger faste regler |
| Fakturamaler | ⬜ | 2 | Logo, farger, bankkonto |
| Kundeportal | ⬜ | 4 | Kunden ser og betaler fakturaer |

### EHF og elektronisk faktura

| Funksjon | I dag | Fase | Merknad |
|---|---|---|---|
| Motta EHF | ⬜ | 2 | Via innkjøpt aksesspunkt; strukturerte data gir nesten 100 % treff |
| Sende EHF | ⬜ | 2 | Påkrevd for å fakturere offentlig sektor |
| Bokføre automatisk fra EHF | ⬜ | 2 | Forslag som i dag, bare uten tolking av bilde |
| Validering av EHF | ⬜ | 2 | Aksesspunktet validerer; vi validerer i tillegg mot PEPPOL BIS 3.0 |

### Bank

| Funksjon | I dag | Fase | Merknad |
|---|---|---|---|
| Import av kontoutskrift (CAMT.053) | ⬜ | 1 | Fil fra nettbanken; ingen avtale trengs |
| Automatisk avstemming og matching | ⬜ | 1 | Regler først (KID, beløp, dato), KI for resten |
| PSD2 / åpen bank (lesetilgang) | ⬜ | 2 | Via lisensiert leverandør, se kap. 6 |
| Flere banker | ⬜ | 2 | Følger av PSD2-leverandøren |
| Betaling og godkjenning fra Bokbuzz | ⬜ | 3 | Betalingsinitiering; banken krever sterk autentisering |

### Lønn og ansatte

| Funksjon | I dag | Fase | Merknad |
|---|---|---|---|
| Utlegg | ⬜ | 2 | Samme flyt som bilag, men refusjon til ansatt |
| Reiseregning | ⬜ | 3 | Statens satser for diett og km |
| Lønn, feriepenger, A-melding | ⬜ | 4 | Stort og regelstyrt. Først integrasjon mot lønnssystem, egen lønn senere |
| Ansattportal og timeføring | ⬜ | 4 | |

### Bilagshåndtering

| Funksjon | I dag | Fase | Merknad |
|---|---|---|---|
| Lese kvittering (OCR + forståelse) | ✅ | – | Multimodal modell, ikke klassisk OCR |
| Opplasting fra mobil | 🟡 | – | PWA med kamera i PR #3 |
| Bilag på e-post | ⬜ | 1 | Egen innboksadresse per selskap |
| KI-klassifisering og MVA-gjenkjenning | ✅ | – | |
| Automatisk kontering | ✅ | – | Forslag + godkjenning; leverandørregler før KI kommer i fase 1 |

### Lager

| Funksjon | I dag | Fase | Merknad |
|---|---|---|---|
| Vareregister | ⬜ | 2 | Trengs for faktura med varelinjer |
| Lagerstyring, innkjøpsordre, kostsporing | ⬜ | 5 | Bygges når kunder etterspør det |

### Integrasjoner og kasse

| Funksjon | I dag | Fase | Merknad |
|---|---|---|---|
| Altinn / Skatteetaten / Brønnøysund | 🟡 | 1–3 | Brreg-oppslag i PR #3; MVA i fase 1 |
| Stripe, Vipps MobilePay | ⬜ | 3 | Utbetalingsrapporter blir bilag + bankmatching |
| Shopify, WooCommerce, Klarna | ⬜ | 3 | Samme mønster: salgsoppgjør per periode |
| Kassesystemer (Gastrofix, Susoft, Front Systems, Shopify POS, Lightspeed, Square) | ⬜ | 5 | Felles kassemodul: Z-rapport / SAF-T Kassa inn, ett bilag per dag |
| Åpent API og markedsplass | ⬜ | 5 | Først når datamodellen har stått stille en stund |

### Rapportering

| Funksjon | I dag | Fase | Merknad |
|---|---|---|---|
| Sanntidsoversikt og nøkkeltall | 🟡 | 2 | «Året så langt» i PR #3; utvides |
| Likviditetsprognose | ⬜ | 3 | Åpne poster + faste kostnader + historikk |
| Egne rapporter og eksport (Excel, PDF, SAF-T) | ⬜ | 1–3 | SAF-T i fase 1, resten senere |

## 4. Faser

Hver fase har en port: vi går ikke videre før kriteriet er nådd.

### Fase 0: Ferdigstille grunnmuren (nå)

- Merge PR #3 (kundeapp ENK + AS) etter at migrasjon 0004 er kjørt i Supabase.
- Drift i Google Cloud (Cloud Run, lagring, Vertex AI EU) etter `docs/OPPSETT.md`.
- **Port:** eier kan logge inn i produksjon, laste opp en kvittering og bokføre den.

### Fase 1: Pilot-MVP (mål: 5–10 ENK og små AS bruker Bokbuzz som eneste regnskap)

Det minste en ekte kunde trenger for å føre et helt år:

1. **Bank:** CAMT.053-import, avstemming med regler, KI-forslag for det som ikke matcher.
2. **Forklaring på hvert forslag:** «Hvorfor 6550?» besvares fra lagret begrunnelse og regelen som ble brukt.
3. **Leverandørregler:** samme leverandør gir samme kontering uten KI-kall (billigere og mer stabilt).
4. **Bilag på e-post.**
5. **Enkel faktura og kreditnota** med KID og PDF, og bokføring av kundefordring.
6. **MVA-melding:** beregning per termin, utkast i appen, innsending via Skatteetatens API.
7. **SAF-T-eksport.**
8. **Assistent (bare lesing):** svarer på spørsmål om eget regnskap og forklarer bilag, uten å kunne endre noe.
9. Drift: virusskanning av filer, daglig forankring av hash-kjeden, gjenopprettingsøvelse, DPA med kundene.

**Port:** treffrate over 80 % på pilotkundenes bilag, én MVA-termin sendt inn uten feil, ingen avvik i
avstemming, partner-regnskapsfører har gått gjennom kontoplan og MVA-koder.

### Fase 2: Paritet med Fiken for ENK og små AS

Kunde- og leverandørreskontro, tilbud, repeterende faktura, purring og rentenota, EHF inn og ut via
aksesspunkt, PSD2-bank via leverandør, utlegg, prosjekt og avdeling, resultat og balanse, årsoppgjør ENK.

**Port:** en ny kunde kan flytte fra Fiken (SAF-T inn) og drive et helt år uten å savne noe vesentlig.

### Fase 3: KI-fordelene (det Fiken ikke har)

- Agentene i kapittel 5 blir proaktive: finner manglende bilag, varsler MVA-risiko og frister,
  foreslår rettelser og forbereder avstemming.
- Samtale med handling: «Lag fakturaer for alle abonnementer» gir et utkast kunden godkjenner.
- Økonomisjef-copilot: likviditetsprognose, lønnsomhet, budsjettforslag, helsescore, finansieringsberedskap.
- Dokumentforståelse utover kvitteringer: kontrakter, låne- og leieavtaler gir forslag til periodisering
  og avskrivning.
- Årsregnskap og skattemelding for AS, betaling fra Bokbuzz, Stripe, Vipps, Shopify, WooCommerce, Klarna.

### Fase 4: Ansatte

Integrasjon mot lønnssystem (lønnsbilag inn automatisk), reiseregning, ansattportal, timeføring.
Egen lønn med A-melding vurderes først når kundegrunnlaget forsvarer det.

### Fase 5: Bredde

Kassesystemer, lager og innkjøp, åpent API og markedsplass, kundeportal.

### Grov tidslinje for én utvikler med KI-hjelp

| Fase | Anslag | Usikkerhet |
|---|---|---|
| 0 | 1–2 uker | Avhenger mest av GCP-oppsett |
| 1 | 3–4 måneder | MVA-API og Maskinporten-tilgang kan ta uker i saksbehandling |
| 2 | 6–9 måneder | EHF og PSD2 avhenger av leverandøravtaler |
| 3 | løpende fra fase 2 | |
| 4–5 | 2028 og senere | Bør vurderes med flere utviklere |

## 5. Agentarkitektur

### Prinsipp: agenter foreslår, mennesker forplikter

Hver handling et system kan gjøre, plasseres i én av fire klasser. Agentene får bare verktøy fra de to
første klassene.

| Klasse | Eksempler | Hvem utfører |
|---|---|---|
| **L – lese** | Saldo, åpne poster, bilag, regelverk | Agent fritt, innenfor kundens selskap |
| **U – utkast** | Konteringsforslag, fakturautkast, MVA-utkast, purreutkast, avstemmingsforslag | Agent lager, lagres som forslag |
| **B – bokføre** | Bokføre bilag, lukke periode, reversere | Bare bruker, via godkjenning (minst to klikk) |
| **E – ekstern** | Sende faktura/EHF, sende MVA-melding, betale, purre | Bare bruker, med eget bekreftelsessteg; betaling i tillegg med bankens sterke autentisering |

Dette er det samme mønsteret som i dag (`proposals` + `review`), bare utvidet til flere typer forslag.
Det betyr at nye agenter ikke trenger nye sikkerhetsmekanismer, bare nye forslagstyper.

### Orkestratoren

```
 Hendelse (bilag, banklinje, frist, spørsmål)
            │
            ▼
   Orkestrator  ── regler først: hvilken hendelse → hvilken agent
            │      KI bare for å tolke fritekst fra brukeren
            ▼
   Fagagent  ── verktøy L og U, egen instruks, eget kostnadstak
            │
            ▼
   Validering  ── skjema, aritmetikk, kontoplan, MVA, tilgang (samme kode som i dag)
            │
            ▼
   Forslag i godkjenningskøen  ──►  Bruker godkjenner (B/E)  ──►  post_voucher / ekstern sending
```

- Orkestratoren er vanlig kode som ruter hendelser via jobbkøen i Postgres. Den er ikke en egen KI som
  styrer de andre; det gjør systemet forutsigbart, testbart og billig.
- Hver agentkjøring logges i en tabell `agent_runs`: agent, modell, instruksversjon, input-hash,
  verktøykall, resultat, kostnad. Forslaget peker på kjøringen, så «hvorfor?» alltid kan besvares.
- Innhold fra dokumenter, e-post og bankdata er **data, aldri instruksjoner**. En agent som leser et
  dokument, kan ikke i samme kjøring kalle verktøy som sender noe ut.
- Kostnadstak per selskap og måned gjelder alle agentene samlet (finnes allerede for bilag).

### Agentene

| Agent | Jobb | Bygger på | Fase |
|---|---|---|---|
| **Bilagsagent** (Accounting) | Lese bilag, foreslå kontering, forklare | Finnes i dag (`proposals`) | ✅ |
| **Bankagent** | Matche banklinjer mot bilag og fakturaer, foreslå bilag for resten, finne manglende kvitteringer | Regler + KI for rest | 1 |
| **Assistent** | Svare på spørsmål på enkel norsk, forklare bilag og regler | Bare L-verktøy | 1 |
| **MVA-agent** | Beregne termin, lage utkast, finne avvik og risiko før innsending | Regler + KI-forklaring | 1 |
| **Fakturaagent** | Lage fakturautkast fra samtale, abonnement og tilbud | U-verktøy | 2 |
| **Innfordringsagent** (Collection) | Følge opp ubetalte fakturaer, lage purreutkast | Inkassolovens regler | 2 |
| **Kontrollagent** (Compliance + Audit) | Finne feil, manglende dokumentasjon og frister; forberede avstemming og årsoppgjør; svarutkast til revisor | Regler + KI | 3 |
| **Økonomisjefagent** (CFO) | Prognose, lønnsomhet, budsjett, helsescore | L-verktøy + beregninger | 3 |
| **Skatteagent** | Skattemelding og næringsspesifikasjon, innsikt i skatteplanlegging | Grupperingskoder | 3 |
| **Lønnsagent** | Lønnsbilag inn, kontroll av A-melding | Integrasjon først | 4 |

Kontroll og revisjon er slått sammen til én agent i starten. De bruker de samme dataene og reglene, og
færre agenter er lettere å teste for én utvikler.

### Hvordan vi vet at agentene er gode nok

- **Gullstandard-sett:** 200 ekte, anonymiserte bilag med fasit fra regnskapsfører. Hver endring i instruks
  eller modell kjøres mot settet før den tas i bruk.
- **Treffrate per agent** vises i et internt dashboard og styrer hvor mye som vises som «sikkert» i appen.
- **Ingen agent får nye verktøyklasser** uten egen gjennomgang.

## 6. Integrasjoner som krever avtaler eller godkjenning

| Integrasjon | Hva som kreves | Anbefaling | Ledetid (grovt) |
|---|---|---|---|
| **Maskinporten** (grunnlag for Skatteetaten og Altinn) | Avtale med Digdir som virksomhet, virksomhetssertifikat eller nøkkel | Søk tidlig i fase 1 | Uker |
| **MVA-melding** (Skatteetaten) | Registrering som systemleverandør, test i Skatteetatens testmiljø, sluttbruker må delegere i Altinn | Bygg i fase 1 | Uker |
| **SAF-T Regnskap** | Ingen avtale; må følge Skatteetatens format og validering | Bygg i fase 1 | – |
| **Skattemelding næring / årsregnskap** | Systemleverandørtilgang hos Skatteetaten og Brønnøysundregistrene | Fase 2–3 | Uker |
| **PEPPOL / EHF** | Å bli eget aksesspunkt krever avtale med norsk PEPPOL-myndighet, sertifisering og drift døgnet rundt | **Kjøp aksesspunkt som tjeneste** fra en eksisterende leverandør | Dager–uker |
| **PSD2 kontoinformasjon** | Egen lisens fra Finanstilsynet som kontoinformasjonstjeneste, eller avtale med lisensiert aggregator | **Bruk aggregator** (velges i fase 2 ut fra pris og bankdekning) | Uker |
| **PSD2 betaling** | Lisens som betalingsfullmektig eller aggregator med betalingsinitiering | Aggregator, fase 3 | Uker |
| **A-melding** | Maskinporten + Altinn; tung regelmasse (lønn, skattetrekk, arbeidsgiveravgift) | Integrer mot lønnssystem først | Måneder |
| **Vipps MobilePay, Stripe, Shopify, WooCommerce, Klarna** | Partner- eller API-avtale per leverandør, vanligvis enkel | Fase 3 | Dager |
| **Kassesystemer** | Avtale per leverandør; noen krever partnerstatus | Felles kassemodul, fase 5 | Varierer |
| **Brønnøysundregistrene (oppslag)** | Åpent API | Finnes i PR #3 | – |

Detaljer om krav og prosess må sjekkes mot kildene (Digdir, Skatteetaten, Finanstilsynet) når vi starter
hver integrasjon. Dette er en planleggingsoversikt, ikke juridisk vurdering.

## 7. Grenser for compliance

Disse reglene styrer alt vi bygger, også agentene:

1. **Kunden godkjenner hvert bilag.** Godkjenningen logges med bruker, tidspunkt, hva som ble vist og hva
   som ble endret. KI kan gjøre godkjenningen rask, men aldri unødvendig.
2. **Ingen bokføring uten dokumentasjon** (bokføringsloven § 10 og bokføringsforskriften kap. 5).
   Bankagenten foreslår, men et bilag uten dokumentasjon flagges som mangel.
3. **Sporbarhet og endringer** (bokføringsforskriften). Bokførte bilag endres aldri; feil rettes med nytt
   bilag. Gjelder også KI-forslag som ble godkjent.
4. **Oppbevaring.** Primærdokumentasjon og regnskap i fem år, i lagring som ikke kan slettes, og eksport
   til kunden (SAF-T + originalfiler) når som helst.
5. **Personvern.** Bokbuzz er databehandler for kunden; DPA med hver kunde; KI kjøres i EU (Vertex AI EU)
   uten at data brukes til trening.
6. **Innsending til myndigheter** (MVA, A-melding, skattemelding) gjøres alltid av kunden med eget
   bekreftelsessteg. Agentene lager utkast og forklarer.
7. **Råd og svar fra assistenten** merkes som veiledning, med henvisning til regel eller kilde der det finnes.
   Usikre svar sier at de er usikre og foreslår å spørre en regnskapsfører.
8. **Betaling** krever alltid bankens egen sterke autentisering. Bokbuzz lagrer aldri bankpassord.

## 8. Foreslått neste byggesteg

Grunnmuren må være i drift før noe annet gir verdi for en kunde. Deretter anbefales:

**Neste steg: Bankagent v1 + forklaring på hvert forslag**

1. CAMT.053-import (fil fra nettbanken), lagret uforanderlig som dokument.
2. Avstemming med regler: beløp, dato, KID og tekst mot bokførte bilag.
3. Forslag i godkjenningskøen for banklinjer uten bilag (med flagg «mangler kvittering»).
4. Felt `explanation` på alle forslag: kort begrunnelse på enkel norsk for valgt konto og MVA-kode,
   vist i appen som «Hvorfor?».

Hvorfor dette først: uten bankavstemming kan ingen pilotkunde føre et helt år, og forklaringen er den
synlige forskjellen fra Fiken som koster minst å bygge. Begge bygger på mekanismer som allerede finnes
(dokumenter, jobbkø, forslag, godkjenning).

Alternativer, hvis eier heller vil det: MVA-melding først (krever Maskinporten-tilgang, så søknaden bør
uansett sendes nå), eller assistenten først (mest synlig, men gir mindre verdi uten bankdata).
