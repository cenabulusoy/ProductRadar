# Sprint 4.3 — V1 versus V2 Comparison

## Resultaat en grens van bestaande gegevens

V1 blijft de dashboardengine. Vergelijking is uitsluitend optioneel en read-only.
De rekenmodules van v1, Financial v2 en Scoring v2 zijn ongewijzigd. Er zijn geen migraties,
product-/snapshotupdates, dependency-updates, refreshprocessen of nieuwe scoregewichten.

**De huidige database bevat geen opgeslagen volledige Financial v2-inputsets.** De legacyvelden
kennen geen expliciete btw-basis, volledige kosten, tariefcontext, invoerdatum of betrouwbare
missing-versus-zerobetekenis. Daarom zet de adapter geen legacybedragen automatisch om naar
financiële v2-inputs. Ook verkoopranges missen scope/methode/datum en worden niet als officieel
verkoopbewijs of als gedocumenteerde v2-schatting doorgegeven.

Concreet: de read-only controle op de acht bestaande producten gaf acht expliciet onvolledige
v2-beoordelingen, nul fouten en nul definitieve v2-scores. De pagina maakt die beperking zichtbaar.
Een volledige numerieke vergelijking is nu alleen onderbouwd met de fictieve acceptatiegegevens;
voor eigen producten is later expliciete financiële invoer/provenance en opslag nodig.

## Concrete beschrijving van de interface

Op de productdetailpagina staat onder de bestaande productkop een paneel **Decision Engine v1
versus v2** met de knop **Vergelijk opgeslagen gegevens**. Pas na klikken wordt de read-only
vergelijking opgehaald. De bestaande v1-kaart, calculator en ProductDNA blijven beschikbaar.

Het paneel toont twee kaarten naast elkaar: v1-score/verdict en v2-score/verdict. Daaronder staan
vijf subscores, positieve/negatieve drivers, caps met uitleg en ontbrekende kritieke inputs.
Risk vermeldt expliciet dat hoger méér risico betekent. Ontbrekende scores heten **Onbekend**;
een cap wordt nooit weergegeven alsof deze een definitieve score is.

Het marktblok toont bron, API-versie, snapshot-ID, meetmoment en leeftijd bij de analyse.
Bij meer dan 24 uur verschijnt een amberkleurige waarschuwing om marktdata te vernieuwen;
de prijsrange heet dan **Historische prijsrange — geen actuele prijs**. Er is geen knop die
stilzwijgend live bol-data ophaalt. De leeftijd wordt getoond ten opzichte van het vermelde
analysemoment; het overzicht is geen live monitor.

Uitklapbare bronuitleg onderscheidt officiële bol-metingen, handmatige/importgegevens,
afgeleide ProductRadar-metrics en schattingen. De bestaande verkooprange staat expliciet als
**Schatting — geen gemeten verkoopcijfer**. Legacy-nullen worden zichtbaar behouden, met uitleg
dat ze importdefaults kunnen zijn; ze worden niet als volledige financiële v2-invoer gebruikt.

Via **Vergelijken · v1/v2** in de navigatie opent `/comparison` een evaluatietabel. Na expliciet
laden toont deze per product v1-score/verdict, v2-score/verdict, Data Confidence en hoofdreden.
De volgorde is vaste product-ID-volgorde, 25 regels per pagina; geen automatische v2-ranking
of v2-filter. Productnamen linken naar het detail. Fouten blijven per rij zichtbaar.

## Backend

- `GET /api/comparison/products/{product_id}`: één opgeslagen product met exacte v1-output en
  compacte v2-presentatie. 404 bij ontbrekend product.
- `GET /api/comparison/products?offset=0&limit=25`: gepagineerde evaluatie, limiet maximaal50,
  vaste `id ASC`-volgorde, total/next_offset en hetzelfde evaluatiemoment per pagina.
- `Cache-Control: no-store`; GET-only. Geen clientinjectie van scores, snapshots of aannames.
- Producten worden via SQLite `mode=ro` gelezen, zonder database-initialisatie. Bestaande
  `read_evidence` levert opgeslagen bol-identiteit en snapshots aan de ongewijzigde v2-engine.
- Ontbrekende database/tabellen worden niet aangemaakt. Technische fouten tonen geen interne
  details. Een onleesbaar product verdwijnt niet stilzwijgend uit de evaluatie.
- De hoofdreden gebruikt vaste prioriteit: veroudering, harde safeguards, onvolledigheid,
  confidence, concurrentie, overeenkomst/andere weging. Dit is uitleg, geen causale attributie.
- Productlezing en snapshotlezing hebben elk een read-only transactie; een gelijktijdige externe
  wijziging kan tussen beide lezingen vallen. Historische analyses worden in deze sprint niet opgeslagen.

## Vijf representatieve fictieve scenario's

De JSON-fixture wordt berekend met beide echte engines en ook door de frontendtests gebruikt.
V1 gebruikt dezelfde geplande prijs van EUR39,95; v2 gebruikt de opgeslagen bol-referentie
EUR24,20 als lager conservatief scenario, met expliciete btw/kosten/provenance.
Deze uitgebreide financiële input bestaat in de fixtures, niet in de huidige producttabel.

| Scenario | V1 | V2 | Confidence v2 | Hoofdreden |
|---|---|---|---:|---|
| Sterke onderbouwde economie | 97 / Kansrijk | 79,96 / Kansrijk | 84,50 | Zelfde verdict, verschillende weging |
| Hoge inkoopkosten, negatieve bijdrage bij marktprijs | 89 / Kansrijk | 24 / Niet inkopen | 84,50 | Bijdrage -EUR2,00; verliescap |
| Sterke marge, geschatte retourreserve | 97 / Kansrijk | 61,76 / Onderzoeken | 58,50 | Lagere kwaliteit financiële bewijsbasis |
| 100 gemeten verkopers versus één handmatig ingevoerde verkoper | 97 / Kansrijk | 74,59 / Onderzoeken | 84,50 | Officiële offers ondersteunen hogere concurrentiedruk |
| Marktmeting vier dagen oud | 97 / Kansrijk | Onbekend / Onderzoeken | 36,75 | Financial v2 behoudt de 24-uursgrens |

V2 reageert aantoonbaar verstandiger op een verliesgevend conservatief scenario en voorkomt
dat een oude prijs als actuele onderbouwing geldt. De vergelijking maakt ook verschillen
tussen een handmatige verkopertelling en actuele opgeslagen bol-aanbiedingen zichtbaar.

Mogelijk te streng: één geschatte kostenpost verlaagt via de minimumkwaliteit de hele financiële
bewijsbasis. Een vier dagen oude maar feitelijk stabiele prijs geeft geen definitieve score.
Dat zijn bestaande beleidskeuzes, in deze sprint niet aangepast. Gelijke verdicts betekenen
niet dat de numerieke scores dezelfde schaal of voorspellende waarde hebben.

## Validatie

- Volledige backend-suite: **279 geslaagd**, waaronder 14 vergelijkingstests.
- Volledige frontend-suite: **50 geslaagd**, waaronder 15 vergelijkingstests.
- Next.js **15.5.26 production build geslaagd**, inclusief `/comparison` en productdetailroute.
- V1-golden outputs exact behouden; bestaande Financial v2- en Scoring v2-regressies behouden.
- Tests gebruiken uitsluitend fictieve gegevens en geïsoleerde tijdelijke testdatabases.
- Gebruikersdatabase voor/na de backend-suite exact dezelfde SHA-256.
- Extra read-only controle: beide nieuwe endpoints HTTP200, acht productregels, nul fouten,
  nul bol-aanvragen en exact dezelfde databasebytes.
- Bestaande deprecationwaarschuwingen voor FastAPI `on_event` en React `react-test-renderer`.

## Aanbevelingen vóór v2 productiebeleid

1. Bouw expliciete financiële v2-invoer en versieerbare opslag met btw, kosten en provenance.
   Geen automatische migratie van ambigue legacywaarden.
2. Voeg daarna gecontroleerde marktverversing toe; behoud de geaccepteerde 24-uursgrens totdat
   een afzonderlijk scenario-/freshnessbeleid is ontworpen en goedgekeurd.
3. Beoordeel de minimumkwaliteitregel voor noodzakelijke schattingen zoals retourreserves aan
   de hand van werkelijke uitkomsten; pas geen gewichten alleen aan om meer Kansrijk te krijgen.
4. Valideer scores op gerealiseerde bijdrage, verkoop en voorraadduur voordat v2 rangschikking
   of inkoopbeleid gaat sturen.

## Bestanden

Gewijzigd: `backend/app/main.py`, `frontend/app/page.tsx`, `frontend/app/globals.css`,
`frontend/components/ProductDetail.tsx`.

Toegevoegd: `backend/app/api/comparison.py`, `backend/app/services/comparison.py`,
`backend/tests/test_comparison.py`, `backend/tests/fixtures/comparison_scenarios.json`,
`frontend/app/comparison/page.tsx`, `frontend/components/DecisionComparison.tsx`,
`frontend/components/DecisionEvaluation.tsx`, `frontend/lib/comparison-types.ts`,
`frontend/tests/decision-comparison.test.cjs`, dit rapport.
