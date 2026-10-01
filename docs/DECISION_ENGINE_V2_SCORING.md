# Sprint 4.2 — Decision Engine v2 Scoring

## Status en scope

Afzonderlijke read-only engine `2.0.0-scoring.1`, configuratie `scoring-nl-new-1`, inputschema `1`.
Gebaseerd op het Sprint 4-ontwerprapport in deze projecttaak (ontwerp op main `d87834b`).
Financial Engine `2.0.0-financial.1` blijft de enige financiële rekenbasis.
V1, ProductDNA, CSV-contracten, productrecords en dashboard blijven ongewijzigd. Geen migratie,
opslag van analyses, automatische bol-aanvragen of dependency-updates.

Dit zijn heuristische rangschikkingsscores, geen voorspelde kansen op verkoopsucces.
Risk is de uitzondering op de richting: **hoger betekent meer risico**.

## Architectuur

- `analysis/scoring_v2_policy.py`: expliciete gewichten, ankers, caps en thresholds.
- `analysis/scoring_v2.py`: gevalideerde invoer, bronselectie, zuivere deterministische berekening.
- `api/decision.py`: één consistente SQLite-leestransactie met `mode=ro`; laadt identiteit en
  product-/marktsnapshots van dezelfde EAN. Geen gebruik van de schrijvende snapshot-service.
- `main.py`: uitsluitend registratie van de nieuwe router.

De engine ontvangt een expliciete `as_of`; geen klok, netwerk of database in de rekenmodule.
Iedere uitkomst bevat de volledige bevroren gebruikte invoer en bronmetingen, financiële output,
configuratie en SHA-256-configuratiehash. Een deterministische `analysis_id` omvat engineversie,
configuratiehash en invoer inclusief `as_of`. Een nieuwe invoer/configuratie/tijd geeft een nieuwe analyse.
Voor replay zijn ook de betreffende engineversie en Financial Engine-versie nodig; oude analyses
mogen later niet stilzwijgend met nieuwe code worden herberekend.

## Formules

`clip(x)=min(100,max(0,x))`. Scoring gebruikt ongeronde Python-getallen; de financiële module
levert haar bestaande Decimal-output op vier decimalen. Presentatie kan op één decimaal afronden;
verdicts worden vóór presentatieafronding bepaald.

### Demand

Twee valide ratingmetingen met dezelfde EAN, bol-ID (ook beide afwezig toegestaan), taal en
endpointversie, 14–60 dagen uit elkaar. Kies de meting het dichtst bij 30 dagen vóór de nieuwste.
Een daling of identiteitsbreuk in de vergelijkbare tussenliggende metingen blokkeert de groeiroute.
De nieuwste mislukte ratingmeting wordt niet vervangen door een oudere succesvolle meting.

`g=30*(N_nieuw-N_oud)/dagen`

`D=clip(100*ln(1+g)/ln(31))`, `qD=0.60*f_ratings`.

Zonder geldige groei: uitsluitend een gedocumenteerde marktverkoopschatting met scope `market`:
`D=clip(100*ln(1+ondergrens_maandverkopen)/ln(501))`, `qD=0.25*f_ratings`.
Schatting en ratinggroei worden niet opgeteld. De ongebruikte schatting blijft als vergelijking zichtbaar.
Alleen een hoog totaal ratingaantal bewijst geen actuele vraag. Geen bron betekent `D=null,qD=0`.

### Competition

Unieke verkopers worden opnieuw uit retailer-ID's geteld; aanbiedingen worden apart geteld.
Gecachte `derived`-totalen worden niet vertrouwd. Alleen volledige NL/NEW/EUR/v10-metingen.
Ontbrekende retailer-ID's, dubbele offer-ID's, gedeeltelijke paginering of ongeldige prijzen
maken de concurrentiemeting onbekend. Een complete lege lijst geeft bekende tellingen 0,
maar **geen Competition-score**.

`C_druk=min(80,100/(1+ln(n)/ln(5)))`, voor `n>=1`.

`L=100` bij even goede/betere levering; `50` bij één dag later; `0` bij twee of meer dagen later.
De expliciete vergelijking vereist dezelfde snapshot, relevante offer-ID, geldige leverdatum
en bevestigde gelijke bestelcondities. Een FBB-label op zichzelf geeft geen bonus.
Onbekende levering blijft `null`, met uitsluitend intern `L=50`.

`C=0.80*C_druk+0.20*L`

`qC=q_markt*(0.80+0.20*q_leververgelijking)`.

De relevante aanbieding is de goedkoopste bol-beste aanbieding; zonder beste-markering de
laagste geldige prijs, identiek aan Financial v2. Prijsrange, relevante aanbieding, fulfilment
en leverinformatie blijven beschikbaar in metrics en bevroren bronmetingen.

### Profitability

Uitsluitend de conservatieve `base` van Financial v2; geen v1-veld of zelf aangeleverde winst.
`pi` is bijdrage per stuk na opgenomen kosten, geen gegarandeerde nettowinst.

`M=clip(100*margepercentage/25)`

`U=clip(100*pi/8)`

`I=clip(100*voorraad_ROI_percentage/75)`

`P=0.50*M+0.30*U+0.20*I`.

ROI kan maximaal 20 punten bijdragen. Ontbrekende financiële inputs geven P onbekend.
Bij expliciet nul landed inkoopkosten berekent Financial v2 wel de bijdrage, maar ROI blijft
onbekend. Deze scoringversie herverdeelt de ROI-weging niet: P en definitieve Opportunity blijven
onbekend totdat een afzonderlijk nul-voorraadkostenprofiel is ontworpen.

`qP=min(kwaliteit noodzakelijke prijs/btw/kosten/commissie-inputs, q_markt)`.
Ook onderliggende vaste commissieprovenance telt mee. Geschatte kosten kunnen qP dus verlagen.
Verlopen kosteninformatie blokkeert een definitieve score; de historische financiële uitkomst
blijft ter uitleg beschikbaar.

### Risk

Operationeel: gemiddelde van vijf expliciete beoordelingen (0,50,100): breekbaarheid, handling,
houdbaarheid/veroudering, leverancier, MOQ/voorraadbeslag. Elk vereist uitleg en gedateerde
provenance. Onbekenden blijven zichtbaar als null en tellen intern als 50 met kwaliteit 0.

Kwaliteit: `R_kwaliteit=clip(100*((b+2)/(N+10))/0.20)`, met b één-/tweesterrenratings.
Dit is geen retourpercentage. Een expliciet lege ratingverdeling biedt geen kwaliteitsbewijs
en blijft onbekend, in plaats van uitsluitend de prior als geobserveerd risico te tonen.

Prijs: `spreiding=(max(referentieprijzen)-min(referentieprijzen))/mediaan(referentieprijzen)`.
`R_prijs=clip(100*spreiding/0.20)`.
Gebruik de nieuwste geldige meting per UTC-dag, minimaal 3 dagen over 7 dagen, in een venster
van 90 dagen. De referentieselectiemethode moet gelijk blijven (beste versus laagste fallback).
Kwaliteit 0.5; vanaf 7 meetdagen over 30 dagen kwaliteit 1, steeds vermenigvuldigd met actuele
versheid van de nieuwste geldige meting.

`R=0.50*R_operationeel+0.30*R_kwaliteit+0.20*R_prijs`.
Ontbrekende componenten krijgen uitsluitend intern 50; als alle componenten onbekend zijn,
blijft ook R null. Componenten en kwaliteitsfactoren worden altijd apart geretourneerd.

`qR=0.50*q_operationeel+0.30*q_kwaliteit+0.20*q_prijs`.

### Data Confidence

`q=bronkwaliteit*volledigheid*versheid`.
Officiële servermetingen kwaliteit 1; gedocumenteerde financiële handmatige invoer 0.9;
extern afgeleide ongedocumenteerde invoer 0.2; schattingen 0.25. Gedocumenteerde operationele
beoordelingen/leververgelijkingen krijgen kwaliteit 1 volgens de ontwerpscenario's, maar zijn
uitdrukkelijk door de gebruiker verklaard, niet onafhankelijk geverifieerd.
De API accepteert geen caller-declared `official_measured`; die classificatie komt uit opgeslagen bol-metingen.

`f=1` tijdens de vrije periode; daarna `f=2^(-(leeftijd-vrij)/halfwaardetijd)`;
na de maximumleeftijd of bij toekomstige/ongeldige tijden `f=0`.

| Groep | Vrij | Halfwaardetijd | Maximum |
|---|---:|---:|---:|
| Markt en leververgelijking | 1 dag | 3 dagen | 14 dagen |
| Ratings/schatting | 7 | 30 | 90 |
| Financiële invoer | 7 | 30 | 90 |
| Operationeel | 30 | 90 | 365 |

`Q=100*(0.25*qD+0.20*qC+0.40*qP+0.15*qR)`.
Onvolledige offers leveren geen deels betrouwbare volledige concurrentietelling: qC=0.

### Opportunity

`D_eff=50+qD*(D-50)`; analoog voor C en P.
`S_eff=50+qR*((100-R)-50)`.
Onbekende subscores gebruiken uitsluitend intern 50 en blijven publiek null.

`basis=0.25*D_eff+0.20*C_eff+0.40*P_eff+0.15*S_eff`

`voor_caps=clip(basis-0.20*(100-Q))`.

Pas alle toepasselijke caps toe; de laagste wint. Geen aanvullende positieve floor.

| Regel | Cap / gevolg |
|---|---|
| Expliciet bevestigde verkoopblokkade | 0, Niet inkopen |
| Geldige basisbijdrage <=0 | 24, Niet inkopen binnen dit scenario |
| Stressbijdrage <=0 | 49 |
| D<35 en qD>=0.50 | 49 |
| R>=75 en qR>=0.60 | 49 |
| qD<0.50 | 64 |
| Q<75 | 64 |
| Q<50 | 49; Onderzoeken wegens onvoldoende bewijs |
| Niet alle gereedheidsvoorwaarden | 74 |
| Kritieke financiële inputs/identiteit/bruikbare actuele marktprijs ontbreken | Definitieve score null; Onderzoeken |

Bevestigde blokkades gaan boven onbekende data. Een werkelijk berekende niet-positieve
basisbijdrage geeft Niet inkopen voor dat financiële scenario; bij kritieke ontbrekende
bewijsvelden blijft de definitieve numerieke score null.

Kansrijk vereist: Opportunity>=75, Q>=75, qD>=0.50, qP>=0.80, qC>=0.80, qR>=0.60,
volledige marktprijs maximaal 24 uur oud, P>=60, marge>=10%, positieve stressbijdrage,
R<50 en geen blokkade of kritieke ontbrekende inputs.

Verdictvolgorde: blokkade/basisverlies → Niet inkopen; ontbrekende kritieke data of Q<50 →
Onderzoeken; alle Kansrijk-voorwaarden → Kansrijk; score>=60 → Onderzoeken;
40<=score<60 → Twijfel; lager met voldoende gegevens → Niet inkopen.

## API en output

`POST /api/decision/v2/analyze`

```json
{"ean":"9781538744017","inputs":{"financial":{}}}
```

Dit minimale voorbeeld retourneert bewust onbekende financiële scores. `inputs.financial`
gebruikt exact het Financial v2-inputmodel, uitsluitend `scenario_mode=conservative`.
Optioneel: `operational` met de vijf velden, `demand_estimate`, `delivery`, `sales_block`.
Alle aangeleverde bewijsvelden vereisen bron, herkomsttype, tijdstip en uitleg waar relevant.
De API accepteert geen door de client aangeleverde bol-snapshots of vooraf berekende subscores.

Response: `{ean, analysis_v2}` met:

- engine-, schema- en configuratieversie, configuratiehash, deterministische analysis-ID, as_of;
- alle vijf `subscores`, `input_quality`, effectieve scores, gewogen bijdragen en confidenceaftrek;
- `opportunity_before_caps`, nullable `opportunity_score`, verdict en redencode;
- alle safeguards met cap en begrijpelijke uitleg, positieve/negatieve drivers;
- ontbrekende kritieke inputs, onbekende signalen en ontbrekende gereedheidsvoorwaarden;
- ongewijzigde Financial v2-output, bron-/afgeleide marktmetrics en risicocomponenten;
- inputprovenance, volledige configuratie en `frozen_evidence` voor replay.

`Cache-Control: no-store`. Ontbrekende database/tabellen maken geen database aan; ontbrekende
metingen leveren onbekende scores. Databasefouten geven een generieke 503. Ongeldige EAN,
invoer of toekomstige handmatige provenance geeft 422. Meer dan 2000 snapshots per tabel
wordt expliciet geweigerd (422), nooit stilzwijgend afgekapt. Geen analyses worden opgeslagen.

## Acceptatiescenario's

Zelfde fictieve basis als het ontwerp: bruto 24.20, btw21%, commissie .58+10%, fulfilment3,
reserve1, overige expliciet0. `pi=13-K`, `pi_stress=10.842-K`. Operationele score20,
ratingrisico20 (90 ratings, 2 negatief), prijsrisico20; qR=.9, leververgelijking100.

| Scenario | K | Verkopers | D | P | Q | Opportunity | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| A Hoge vraag, drukke markt | 7 | 20 | 100 | 92.5 | 84.5 | 73.34 | Onderzoeken |
| B Weinig concurrentie, slechte marge | 12 | 1 | 100 | 15.97 | 84.5 | 49 | Twijfel |
| C Sterke marge, afzetschatting | 3 | 3 | 100 geschat | 100 | 75.75 | 64 | Onderzoeken |
| D Hoge vraag, verlies | 15 | 3 | 100 | 0 | 84.5 | 24 | Niet inkopen |
| E Sterke economie en vraagsignaal | 3 | 3 | 100 | 100 | 84.5 | 79.96 | Kansrijk |
| F Markt vier dagen oud | 3 | 3 | 100 | onbekend | 36.75 | onbekend | Onderzoeken |
| G Zwak actueel vraagsignaal | 3 | 3 | 20.18 | 100 | 84.5 | 49 | Twijfel |

F wijkt af van het oude ontwerprekenvoorbeeld: Financial v2 accepteert maximaal 24 uur oude
marktprijzen en blijft ongewijzigd. Competition blijft historisch bruikbaar met lagere kwaliteit,
maar er is geen actuele financiële basis. Ook de versheid van de leververgelijking en de nieuwste
prijsrisicometing wordt consequent meegenomen. Het ontwerpvoorbeeld deed dat laatste niet overal.

## Expliciete verduidelijkingen / afwijkingen

1. **Scenario F — expliciet geaccepteerd bij afronding van Sprint 4.2:** een marktmeting ouder dan 24 uur levert geen actuele Opportunity Score op (null in plaats van 64 in het vierdagenvoorbeeld). Financial Engine v2 behoudt zijn bestaande 24-uursveiligheidsgrens. Een dated_market_scenario, refreshlaag of andere uitbreiding valt buiten deze sprint.
2. **Nul landed kosten:** geen herverdeelde ROI-score; P/Opportunity null. Een onderbouwd
   nul-kostenbedrijfsmodel vereist later een expliciet scoreprofiel.
3. **Risico-onderbouwing:** de niet numeriek bepaalde term 'voldoende onderbouwd' voor de
   hoge-risicocap is ingevuld als qR>=0.60, gelijk aan de Kansrijk-gereedheidsgrens.
4. **Levering:** expliciet gedocumenteerde vergelijking van dezelfde aanbieding/bestelcondities;
   geen automatische claim op basis van FBB/FBR of losse datums zonder bestelcontext.
5. **Geen ratings:** bekende nul ratings geeft geen vastgesteld kwaliteitsrisico; de onbekende
   component gebruikt uitsluitend intern de neutrale prior, met kwaliteit0.
6. **Bronintegriteit:** officiële labels uitsluitend uit servergeladen snapshots; handmatige
   bewijsverklaringen zijn niet onafhankelijk geverifieerd.
7. **Prijsrisico:** 90 dagen historievenster, nieuwste geldige meting per UTC-dag en dezelfde
   referentieselectiemethode. Deze selectiedetails waren nog niet uitgewerkt in het ontwerp.

De ankers zijn niet empirisch gekalibreerd. Ratinggroei bewijst geen verkoopvolume of eigen
afzet. Er is geen dashboardmigratie en geen automatische inkoopbeslissing.

## Tests

Acceptatietests leggen A–G vast, plus verlies/stress, extreme ROI, ontbrekend versus nul,
onvolledige/ongeldige offers, dubbele retailers, ratingbreuken, bronveroudering, operationele
risico's, identiteitsconflicten en deterministische replay. V1 wordt exact tegen de bestaande
zes golden outputs getest; Financial v2 tegen negen vooraf vastgelegde volledige outputs.
API-tests vergelijken databasebytes, bestaande productanalyses en financiële output vóór/na
de scoringaanvraag en controleren dat er geen extra bol-aanvragen plaatsvinden.

Validatie uitgevoerd op 1 oktober 2026:

- Volledige backend-suite: **265 geslaagd**, waaronder 75 nieuwe scoringtests.
- Volledige frontend-suite: **35 geslaagd**.
- Next.js **15.5.26 production build geslaagd**, inclusief typecontrole en alle routes.
- `git diff --check` geslaagd; secretscontrole zonder bevindingen.
- Bestaande waarschuwingen: FastAPI `on_event` en React `react-test-renderer` deprecations.
- Geen live bol-verkeer, geen databasewijzigingen, geen commits/push/merge.
