# Sprint 5.2 — Historical Discovery Monitoring

Branch `feature/discovery-monitoring`, vanaf actuele main `0f4271813c7ea19bcc02966e31d41cb12e773c86`. Implementatie en gecontroleerde pre-commit praktijktest zijn afgerond. De eerste echte monitoringrun is op 10 oktober 2026 uitgevoerd; regressie-, concurrency- en leasegevallen zijn zonder aanvullende live calls in tijdelijke testdatabases/fixtures getest.

## Architectuur en database

Nieuwe centrale `discovery_monitoring.run(context_id, request_id, client)` voert een expliciete, begrensde run uit. De API/UI gebruiken deze service; een toekomstige scheduler kan dezelfde service aanroepen, maar er is nu geen scheduler/background automation. De bestaande BolClient, Product List-provider, catalogus-, ratings- en offersparser blijven ongewijzigd. Monitoring schrijft geen bestaande producten, financial profiles, bol-identiteiten/snapshots of Sprint 5.1-discoveryobservations. De huidige discoverylabels/coverage blijven exact hetzelfde. Nieuwe metingen staan in hun eigen historische ledger en worden niet automatisch Decision-inputs.

Vier additieve tabellen:

- `discovery_monitoring_contexts`: id, naam, immutable canonical parameters JSON, unieke contexthash, created_at.
- `discovery_monitoring_watchlist`: context_id/candidate_id uniek, followed_at; maximaal vijf kandidaten per context. Expliciet volgen/ontvolgen verandert geen historie.
- `discovery_monitoring_runs`: request UUID, context, started_at/lease_until/completed_at, lifecycle-status, frozen watchlist en resultaat/measurement references. Alleen runlifecycle wordt bijgewerkt.
- `discovery_monitoring_measurements`: id, context/candidate/EAN, runreferentie, echt meetmoment, exacte parameters, fingerprint en append-only payload. Unieke (context,candidate,fingerprint) voorkomt een identieke historische meting. Index op context/candidate/measured_at/id.

Migratie draait herhaalbaar/additief in de normale startuptransactie. Tests passen deze op tijdelijke databases toe. Bestaande echte schema/data/sequences blijven gelijk aan de eerdere gevalideerde uitgangssituatie. De echte migratie is op 10 oktober 2026 na een nieuwe, geverifieerde backup toegepast; zie de praktijktest hieronder.

## Zoekcontext

Context bevat zoekterm en/of category-ID, NL, RELEVANCE, pagina 1, taal nl en lege filterRanges/filterValues. De scope is bewust gelijk aan de bewezen Sprint 5.1-provider; andere landen/sorts/pagina's/filters worden niet geveinsd. Parameters zijn immutable; een andere query is een andere context. Naam wijzigen via opnieuw dezelfde parameters bewaren overschrijft niets: bestaande context wordt geretourneerd. De volledige parametershash bepaalt identiteit, geen titel/merkheuristiek.

Een Product List-positie heet **contextgebonden lijstpositie**. Het is geen bol-ranking, sales rank of populariteitsrang. Niet waargenomen betekent uitsluitend ontbrekend binnen deze ene query/pagina/meetcontext, niet verdwenen uit het assortiment of geen verkopen.

## Meetflow, fouten en concurrency

1. Context expliciet bewaren, zonder live call.
2. Bestaande discoverykandidaat expliciet volgen, maximaal vijf; geen financieel profiel of products-record aangemaakt.
3. Opnieuw meten met UUID: atomische SQLite BEGIN IMMEDIATE-reservering, frozen watchlist, globale monitoringlease 75 minuten.
4. Eén Product List-pagina via bestaande provider; uitsluitend gevolgde EANs krijgen catalogus/ratings/offers via de bestaande BolClient.preview-parser.
5. Append-only points en final runresultaat worden atomisch opgeslagen. Oude punten nooit gewijzigd. Previews/ratings/market behouden hun bronmeetmoment; er worden geen oude timestamps bijgewerkt om freshness/groei te creëren.

De enrichmentproxy bewaart geen eigen token en hergebruikt het bestaande clienttransport/OAuth/parser. Grenzen: vijf EANs, maximaal vijf offerpagina's per EAN en 35 logische GET-operaties per run. Als de offerteketen niet binnen deze grens compleet is, wordt de data partial/unavailable; geen lage concurrentie afgeleid. Bestaande 401-tokenretry en rate-limitbackoff blijven bestaan; de logische callgrens is geen telling van OAuth/401-transportpogingen. Geen automatische pagina's voor Product List voorbij pagina 1, geen brede crawl, geen White Spots-call.

De bestaande Sprint 5.1-processlock beschermt discovery-acties binnen één proces. De SQLite-lease beschermt monitoringruns ook over verschillende workers/contexten. Dezelfde voltooide UUID retourneert hetzelfde resultaat zonder nieuwe bol-call. Een andere UUID tijdens een geldige lease geeft 409. Bij netwerkmelding bewaart de UI dezelfde UUID voor veilig terugvragen; bij onderbreking na lease-expiry kan de gebruiker expliciet een nieuwe aanvraag voorbereiden. Verlopen running leases worden bij een volgende reserve interrupted. Een te laat oud resultaat wordt geweigerd, niet alsnog succesvol opgeslagen. Onderbroken/running runs verschijnen als onbekende historische markers; ze verdwijnen niet stilzwijgend achter een oude goede meting.

Mislukte Product List geeft failed points en start geen enrichment. Partial list: afwezigheid unknown, niet not_observed. Complete list zonder gevolgde EAN: not_observed, positie null; afzonderlijke EAN-enrichment kan nog wel echte marktdata meten. Een gedeeltelijk mislukte enrichment bewaart bruikbare afzonderlijke endpointdata, maar incomplete endpoints leveren geen delta. Oude succespunten blijven zichtbaar. Onverwachte procesonderbreking blijft als lease/status expliciet; geen gefabriceerde brondata.

## Provenance en meetpayload

Point bevat EAN/candidate, exacte queryparameters, list_measured_at/status/completeness/errorcode/positie, volledige veilige preview (catalogus, ratingverdeling/count, offers en fulfilment/leverinformatie, API-versies, meetmomenten, endpointstatus/warnings), overall status en provenance. Officiële lijst-/catalogus-/ratings-/offerdata is official_measured. Contextpositie, tellingen, historical deltas en summary zijn derived. Een mislukte lijstpoging is een derived statusmarker, geen gemeten productfeit. Geen estimated maandverkopen of Demand Score.

## Historische regels (discovery-history/1)

Vergelijk alleen dezelfde EAN en exacte contextparameters bij een positief interval. Een conflicterend bekend bol-product-ID blokkeert de vergelijking. Geen fallback naar oudere goede data wanneer de laatste point onvolledig is: betreffende metric blijft null, eerdere punten blijven historie.

- Rating count delta: current minus previous, uitsluitend bij complete vergelijkbare v10/nl-ratingevidence met correcte EAN/endpointstatus/meetmoment en volledige vijfsterrenverdeling. Ontbrekende buckets worden niet als nul aangevuld. Negatieve delta blijft zichtbaar, maar wordt geen negatieve verkoop/groei.
- Rating growth: delta / interval_days en 30 × delta / interval_days, alleen bij 14–60 dagen en niet-negatieve delta. Deze grens sluit aan bij de bestaande v2-filosofie zonder engine/policy te wijzigen. De summary kan de dichtstbijzijnde geschikte oudere anchor gebruiken; geen brug over een ontbrekende/incomplete ratingpoint. Laatste delta blijft de verandering sinds vorige meetpoint.
- Seller/offer delta: verschillen uit onderliggende volledig gevalideerde NL/NEW/EUR/v10-offers, via de bestaande observed_market-afleiding. Volledige expliciete lege offers zijn bekend nul; prijs blijft null. Partial/failed offers zijn onbekend, nooit nul.
- Prijsdelta/min/max: absolute EUR-verschillen met Decimal-afleiding, uitsluitend complete meetparen. Historische validatie gebeurt op het werkelijke meetmoment; dit maakt historische prijzen niet actueel en verandert de 24-uursregel niet.
- Beste-offerwisseling: alleen wanneer beide metingen een identificeerbare echte bestOffer hebben; geen verwisseling met lowest-offer fallback.
- Contextpositie delta: nieuw minus oud, uitsluitend observed + complete list bij dezelfde context en een nieuw list_measured_at. Positieve delta betekent hoger positienummer, geen berekende populariteit. Niet waargenomen/partial/failed = null.
- Fulfilment: vergelijking van bekende methodes van de relevante aanbiedingen. Leververandering: bekende min/max kalenderlead vanaf het UTC-meetdatumreferentiepunt, geen absolute datums door elkaar vergelijken. Dit is een indicatieve kalendervergelijking, geen gecontroleerde bestelconditie/werkdagen- of bezorgprestatiemeting; geen automatisch scoregebruik.

Null = onbekend/onvergelijkbaar. 0 of false = daadwerkelijk geen gemeten verschil. Metric reasons en bronreferenties maken dat onderscheid uitlegbaar. Geen financiële berekeningen, Opportunity Score of automatische inkooplabels.

## Read-only demand evidence

Summary per candidate/context: rating_history onvoldoende/bruikbaar, aantal rating-/complete marktmeetpunten, seller/price-trend beschikbaarheid, contextgebonden list-history, laatste delta en eventueel geschikte ratinggrowth-anchor. actual_sales_evidence, estimated_monthly_sales en demand_score blijven null. Een bruikbare meetreeks met nul groei is geen bewijs van hoge vraag.

Minimumadvies: **twee** complete vergelijkbare ratingmetingen met **14–60 dagen** ertussen zijn slechts de technische ondergrens voor een descriptief groeisignaal. Voor betekenisvolle vervolgprioritering liever **minimaal drie metingen verspreid over 21–30 dagen**, met stabiele identiteit/scope en zonder ontbrekende tussenpunten. Verzamel markt/aanbiedingen en vaste-contextlijstposities bijvoorbeeld dagelijks of meerdere keren per week; minimaal drie complete punten over minstens zeven dagen voor beschrijvende markttrends. Dat interval is een advies, geen nieuwe engine-drempel. Ratings blijven een proxy, geen verkooptelling. Een betrouwbare volume-estimator vereist daarnaast kalibratie tegen echte afzetgegevens.

## API en UI

- GET `/api/discovery/monitoring/contexts`: contexts/watchlists/laatste run/derived lease-expiry; geen live call/migratie.
- POST dezelfde route: context bewaren.
- POST `/contexts/{id}/watchlist`: expliciet volgen/ontvolgen.
- POST `/contexts/{id}/runs`: de centrale handmatige run, UUID-idempotency.
- GET `/contexts/{id}/candidates/{candidate_id}/history`: points plus derived vergelijking/demand evidence; schrijft niets.

Alle routes onder bovenstaande monitoringprefix en responses no-store. Er is geen API om caller-injected official measurements of historische datums op te slaan.

Op /discovery: contextnaam/query/category-ID opslaan, context kiezen, geselecteerde kandidaat volgen, watchlist met EANs en laatste run, Opnieuw meten, status laden en expliciet leaseherstel. Historie toont meetmoment/status/niet-waarneming, ratingaantal, complete provenance in optionele details, alle metric deltas/reasons, ratinggroei bijvoorbeeld +8 ratings in 21 dagen en ontbrekende sales evidence. Geen scheduler, geen v2-dashboardmigratie, geen geschatte verkoopflow. Sprint 5.1-unitcomponenttests isoleren de nieuwe child; eigen monitoringtests testen die child apart.

## Validatie en beperkingen

Volledige backendtests: **387 geslaagd** (351 bestaande + 36 nieuwe). Volledige frontendtests: **97 geslaagd** (85 bestaande + 12 nieuwe). Next.js 15.5.26 production build, typecontrole en paginageneratie: **geslaagd**. Git diff --check en whitespacecontrole van nieuwe bestanden: **geslaagd**. Secretscontrole: **105 bestanden, 0 lokale logs, 0 bevindingen**, .env genegeerd. Read-only vergelijking: bestaande gebruikersdatabase-tabellen, gegevens en sequences exact ongewijzigd; uitsluitend additieve discovery-/monitoringstructuren en geautoriseerde eerste monitoringgegevens toegevoegd, integrity_check ok en foreign_key_check leeg. Alleen 11 bedoelde bestanden gewijzigd/toegevoegd, niets staged/gecommit. Bestaande FastAPI en react-test-renderer-deprecationmeldingen blijven; geen dependencywijziging.

Nieuw getest: append-only/herhaalde points, immutable contextdedup, 0/1/14/21/60-dagenratingintervals, onbekend/nul, dalende counts, identity/API-conflict, offer/seller/prijs/bestoffer/fulfilment/leverdelta, partial list/market, not_observed, failed nieuwste point, geen gap-bridging, atomic validation/rollback, concurrent requests/global lease, 75-minutenherstel/late-resultreject, max vijf watchers, pagina-/GET-budget en bestaande OAuth/tokenparser, provenance/no fake sales/no productmutations, veilige UI retry/history/follow/unfollow/lease/error.

Beperkingen: NL/RELEVANCE/pagina 1; geen overige sort/filterproviders. Alleen gevolgde maximaal vijf kandidaten krijgen meetpoints; alle overige resultaten worden niet als extra discoveryimport opgeslagen. Geen echte historische tijd verstreken of gesimuleerd in de gebruikersdatabase. Geen automatic refresh/scheduler, White Spots, impression/rank/placement-client, sales estimator of Decision-inputinjectie. Full history is momenteel niet gepagineerd; retentie/schaal hoort bij latere monitoringarchitectuur. De history-ledger ondersteunt bronmetingen, geen automatisch commercieel oordeel.

Sprint 5.3 voorstel: voortbouwen op de gevalideerde gebruikers-watchlist en gedurende enkele weken echte meetpunten verzamelen, kwaliteitscontrole/gaps en contextstabiliteit. Ontwerp pas vervolgens demand-evidenceprioritering met uitleg en eventuele gecontroleerde ranking/impressioncapability-check. Geen exacte maandverkopen uit alleen ratings; afzetkalibratie apart voorbereiden. 5.3 niet geïmplementeerd.

## Bestanden

Nieuw: backend/app/api/discovery_monitoring.py; backend/app/services/discovery_monitoring.py; backend/app/services/discovery_history.py; backend/tests/test_discovery_monitoring.py; frontend/components/DiscoveryMonitoring.tsx; frontend/tests/discovery-monitoring.test.cjs; dit rapport.

Aangepast: backend/app/core/database.py (startup migratie); backend/app/main.py (router); frontend/components/Discovery.tsx (alleen nieuwe child); frontend/tests/discovery.test.cjs (isolatiechild). Pure v1/Financial v2/Decision v2/policy, freshness, Sprint 5.1-labels/provider/client, snapshots, market refresh, financial profiles, CSV en dependencies blijven ongewijzigd.

## Pre-commit praktijktest — 10 oktober 2026

Voor de normale backendstart is een nieuwe SQLite online backup buiten de repository gemaakt: `productradar-before-sprint52-20261010T092745Z.db` in de lokale Codex-projectmap onder `local-backups`. De backup is geopend en op integrity, foreign keys en volledige schema-/rijgelijkheid gecontroleerd. Geen credentials zijn opgeslagen in het rapport of teststatusregistratie.

De normale applicatiestart paste de vier additieve Sprint 5.2-tabellen en de twee nog ontbrekende Sprint 5.1-discoverytabellen toe. Alle bestaande tabeldefinities, rijen en oorspronkelijke sequences zijn tegen de backup gecontroleerd en intact gebleven. Producten 1–8, financiële profielen, bol-identiteiten, snapshots, marktsnapshots en overige oorspronkelijke gegevens zijn inhoudelijk ongewijzigd. SQLite integrity_check: ok; foreign_key_check: geen fouten.

Context 1: `auto onderhoud`, NL, RELEVANCE, pagina 1. Vijf eerder in Real Discovery Run #1 geverifieerde EAN-identiteiten zijn gevolgd. Er zijn geen oude ratings/offers of fictieve historische meetpunten ingevoerd. De live run verifieerde hun catalogusidentiteit opnieuw.

| EAN | Product | Meetpunt-ID | Aanbiedingen / unieke verkopers | Prijsrange EUR |
|---|---|---|---|---|
| 5407012560150 | OptiMate 6 Select V2 | 1 | 3 / 3 | 125,95–134,95 |
| 9101219300200 | Zonne-energie-druppellader | 2 | 3 / 3 | 100,95–116,73 |
| 9504831936183 | Mini-zekeringassortiment | 3 | 1 / 1 | 14,65 |
| 6090314188178 | Remmenreiniger 400 ml | 4 | 1 / 1 | 14,99 |
| 4065746650083 | Wurth onderhoudsspray | 5 | 1 / 1 | 32,95 |

Exact één gecontroleerde live monitoringrun: OAuth HTTP 200, één Product List-aanvraag HTTP 200 en vijf catalogus-, vijf ratings- en vijf offersaanvragen allemaal HTTP 200. Alle offersketens waren volledig op pagina 1. Geen White Spots, crawl of aanvullende live monitoringrun. Alle vijf kandidaten zijn waargenomen in de context; posities 7, 20, 35, 13 en 33 zijn derived, geen sales ranking. Alle endpoints en de run zijn complete. Werkelijke meetmomenten: 10 oktober 2026 09:28:47–09:28:54 UTC (11:28:47–11:28:54 Nederlandse tijd).

Officiële catalogus-, ratings-, lijst- en offersdata blijven official_measured. Tellingen, positie en historische evidence zijn derived. Vier kandidaten hebben expliciet nul ratings; de remmenreiniger heeft één rating van drie sterren. Ratinggroei, verkoopvolume, verkoopschatting en Demand Score blijven bij dit eerste meetmoment null/onbekend.

De volledige keten context → watchlist → Product List → catalogus/ratings/offers → opgeslagen meetpunten → historie-API → frontend is gecontroleerd. De echte frontendcomponent heeft de opgeslagen context, vijf watchlistkandidaten en vijf echte historie-API-responses via uitsluitend GET geladen en provenance/onbekende demandwaarden correct getoond. Dit was een componentintegratiecontrole, geen handmatige browser-screenshottest.

Een herhaling met dezelfde voltooide UUID retourneerde exact hetzelfde resultaat, zonder extra bol-calls of meetpunten. Offline concurrencytests bevestigden één keten, globale leaseblokkering, herstel na 75 minuten en weigering van late resultaten. Hiervoor zijn geen extra live calls of fictieve gebruikershistorie gemaakt.

Na afloop zijn de echte context, vijf kandidaatidentiteiten, vijf watchlistregels, één voltooide run en vijf eerste meetpunten behouden zoals geautoriseerd. Er waren geen tijdelijke gebruikersdatabase-testrecords om te verwijderen. De tijdelijke testbackend is gestopt. Alleen externe testhulpmiddelen zijn aangepast; geen productiecodefix was nodig.

Na de praktijktest opnieuw: 387 backendtests geslaagd, 97 frontendtests geslaagd, volledige Next.js 15.5.26 production build/typecontrole/paginageneratie geslaagd, git diff --check geslaagd. Secretscontrole: 105 source/tracked bestanden, 0 lokale repositorylogs, 0 bevindingen; backend/.env en backend/data/productradar.db worden door Git genegeerd. Backup en testhulpmiddelen staan buiten de repository. Alleen de 11 bedoelde Sprint 5.2-code-, test- en documentatiebestanden zijn bestemd voor commit; geen database, backup, credentials, tokens, logs of tijdelijke testbestanden.
