# Sprint 5.3B — Product Placement Foundation

Branch feature/bol-product-placement vanaf main 5655ac6fca55b9b0ecda19136aae4af5e609984a. Geen commit/push/merge. Geen dependencywijzigingen. Bestaande gebruikersgegevens blijven ongewijzigd; de additieve migratie is in de hieronder beschreven pre-commit praktijktest toegepast.

## Officieel contract (v10, gecontroleerd 22 oktober 2026)

- [Functionele documentatie](https://api.bol.com/retailer/public/Retailer-API/v10/functional/retailer-api/product-placement.html)
- [OpenAPI](https://api.bol.com/retailer/public/apispec/Retailer%20API%20-%20v10): operationId get-product-placement, ProductPlacementResponse, Category, SubCategory.
- [Rate limits](https://api.bol.com/retailer/public/ratelimits) en [conventies](https://api.bol.com/retailer/public/Retailer-API/conventions.html).

GET https://api.bol.com/retailer/products/{ean}/placement. Verplicht: EAN pathparameter. Optionele country-code query: NL/BE; optionele Accept-Language header: nl/nl-BE/fr-BE. Geen requestbody, geen pagina of follow-upmechanisme. Foundation stuurt expliciet country-code=NL en Accept-Language=nl voor de UI/live proef. Backend accepteert alleen officieel genoemde land-/taalwaarden. Headers: Bearer via bestaande OAuth-client en Accept application/vnd.retailer.v10+json.

Response verplicht url (string) en categories (array). Elke hoofdcategorie vereist categoryId en categoryName (strings). Optionele subcategories-array is nullable. SubCategory heeft optionele/nullable id, name en recursieve subcategories. De verschillende namen van root- en childvelden blijven in de officiële structuur behouden. Meerdere hoofdcategorieën én meerdere takken onder één hoofdcategorie zijn mogelijk. Geen enkele primaire categorie gekozen en geen categorieën samengevoegd.

Er is geen afzonderlijk land/taalveld in de response: query.country_code/language zijn expliciete requestcontext, niet extra gemeten responsevelden. Product-URL en categorietree zijn echte officiële bronvelden. GPC, Product List-querycategorie/positie en webshopplacement zijn drie verschillende begrippen; er wordt niets naar elkaar gekopieerd.

Lege categories=[] is een geldige response mits url als string aanwezig is. Ontbrekende verplichte root-/categoryvelden of verkeerde typen geven 502, nooit een lege succesvolle lijst. Ontbrekende optionele subvelden blijven null; lege/whitespace categorie-ID/-naam/URL wordt null met derived partial-status. Geen ontbrekende niveaus aangevuld. subcategories=null betekent niet aangeleverde kinderen, [] een expliciet lege kindlijst. Een getoond pad claimt geen onbekende onderliggende niveaus. Geldige lege categories is geen bewijs van nul zichtbaarheid/vraag.

Technische veiligheidsgrenzen: maximaal 500 nodes, maximaal 20 recursiestappen; overschrijding geeft een fout zonder gedeeltelijke boom op te slaan. Veilige allowlistparser negeert onbekende extra velden en hergebruikt de bestaande _text-redactie/begrenzing voor bronstrings. Officiële waarden zijn hierdoor gesanitiseerde bronwaarden. Afgeleide status en padpresentatie zijn geen nieuwe officiële categorieclaims.

Gepubliceerde limiet voor GET /retailer/products/{ean}/placement: 50/minuut. Runtime 429/Retry-After gaat via bestaande BolClient-backoff. Limieten zijn veranderlijk. OpenAPI noemt 200/400/404/406; algemene authenticatie-/rechtenfouten 401/403, 429, 5xx en netwerk/timeouts blijven veilig vertaald via de bestaande client. Geen upstream-errorbody of credentials geretourneerd. De adapter doet precies één placement-GET per expliciete aanvraag, zonder automatische 401-herhaling; OAuth-tokenhergebruik blijft behouden. Geen automatische vervolgaanvragen. Accounttoegang wordt niet aangenomen op basis van het contract.

## Architectuur en database

Afzonderlijke placementservice hergebruikt de bestaande BolClient voor token, transport, veilige foutafhandeling en throttling. Geen tweede client of nieuw databroncontract in bestaande engines. fetch valideert EAN-13/checksum en parameters vóór OAuth. Payload bevat ean, retrieved_at, querycontext, official.url/categories, status, derived completeness, http_status en provenance: official_measured / bol Retailer API / v10 / products/{ean}/placement.

Eén additieve tabel discovery_placement_measurements met id, unieke request_id, query_key, EAN, retrieved_at, country_code, language en veilige JSON-payload. Index discovery_placement_ean_history. Migratie herhaalbaar binnen bestaande startuptransactie. Geen ALTER/UPDATE/DELETE op product-, profiel-, snapshot-, ranking- of monitoringtabellen. Tests voor rollback en alle bestaande regressies blijven intact.

UUID-replay geeft dezelfde opgeslagen meting zonder extra call; dezelfde UUID met andere EAN/land/taal geeft 409. Nieuwe expliciete UUID betekent een nieuwe historische meting, ook bij ongewijzigde categorieën: het nieuwe ophaalmoment is echte evidence. Foutieve responses slaan niets op; partial responses zijn afzonderlijke punten en overschrijven oude complete data niet. Proceslock voorkomt dubbele gelijktijdige ketens binnen één backendproces. Geen multiworker lease of scheduler toegevoegd.

- GET /api/discovery/placement/{ean}: maximaal twintig meest recente lokale metingen; geen live call, migratie of opslag.
- POST /api/discovery/placement: ean, country, language, request_id UUID; geen caller-injected categorieën/payload toegestaan. Slaat uitsluitend afzonderlijke nieuwe placementmetingen op.

Alle responses no-store. De echte gebruikersdatabase is tijdens de onderstaande gecontroleerde migratiepraktijktest na een nieuwe backup gemigreerd; de nieuwe tabel blijft leeg.

## Discovery-interface

Nieuwe afzonderlijke component op de discovery-kandidaatdetailpagina. Openen doet uitsluitend GET voor opgeslagen historie. Expliciete knop Webshopplacement ophalen gebruikt één EAN, NL/nl. Loading, veilige foutmelding, UI-lock en UUID-behoud bij onzekere netwerkuitkomst. Late responses kunnen geen andere kandidaat vervangen. Oude metingen blijven met hun echte ophaalmoment zichtbaar, ook bij een nieuwe fout; geen claim van opnieuw actuele gegevens.

Elke root-to-terminal tak uit de aangeleverde boom wordt afzonderlijk getoond: categoriepad 1, 2, etc. Deze padpresentatie is derived; categorie-ID's/namen zelf official_measured. Product List-zoekcontext, GPC en webshopcategorieën worden expliciet onderscheiden. Ontbrekende namen/ID's zijn Onbekend. Productlink alleen voor HTTPS bol.com/subdomeinen zonder userinfo; nooit javascript of externe lookalike-hosts. Bronstrings zijn tekst/React-escaped.

## Live capability — exact één aanvraag

Na 40 geslaagde eerste offline placementtests uitgevoerd op 22 oktober 2026. EAN 5407012560150 (OptiMate), country-code NL, Accept-Language nl, Accept v10. OAuth HTTP 200; exact één placement-GET HTTP 200. Geen andere geauthenticeerde endpointcalls, retry, crawl of bulk.

Rootvelden daadwerkelijk: url en categories. Hoofdcategorievelden: categoryId/categoryName/subcategories. Bronboom bevat één hoofdcategorie met twee aparte paden:

1. Auto & Motor (43646) → Autoaccessoires (43647) → Autogereedschap (43657) → Acculaders (30743).
2. Auto & Motor (43646) → Motoronderhoud & -onderdelen (43651) → Acculaders voor motor (72612).

Product-URL: https://www.bol.com/nl/nl/p/optimate-6-select-v2-12v-6a-lader-tm-370-v2-intelligente-9-traps-lader-onderhoud-voor-agm-gel-std-efb-en-lifepo4-herstelt-ontladen-batterijen-vanaf-0-5v/9300000272004749/

retrieved_at: 2026-10-22T13:54:39.799338+00:00. Status complete. Parser verwerkte de echte volledige boom correct, geen contractafwijkingen. Accounttoegang bevestigd voor deze EAN/NL/nl-aanvraag; geen algemene garantie voor alle producten/landen. Nieuwe null-normalisatie is daarna uitsluitend offline op fixtures geverifieerd; de geldige live bronwaarden worden daardoor niet veranderd. Geen extra live proef gedaan.

Volledige keten API → parser → tijdelijke SQLite-opslag → read-only API is gecontroleerd met de live response. De daadwerkelijke frontendcomponent toont beide categoriepaden, productlink en provenance correct met dit resultaat, zonder netwerkcalls. Dit is een componentintegratiecontrole, geen handmatige browserscreenshottest. Tijdelijke database verwijderd. Echte gebruikersdatabase was direct vóór/na byte-voor-byte gelijk; alle tien monitoringmeetpunten zijn behouden.

## Validatie, scope en beperkingen

Volledige backendtests: 475 geslaagd (434 bestaande + 41 placementtests). Volledige frontendtests: 115 geslaagd (105 bestaande + 10 placementtests). Next.js 15.5.26 production build inclusief types/paginageneratie geslaagd. Alleen bestaande FastAPI/react-test-renderer deprecationmeldingen, geen nieuwe testwaarschuwing.

Tests: één/multiple roots en branches, lege response, optionele nullwaarden, ontbrekende verplichte velden, lege strings, invalid EAN vóór OAuth, land/taal, HTTP-fouten zonder retry/secrets, idempotency/UUID-conflict, append-only historie, partial/failure zonder overwrite, veilige boomgrenzen, één gelijktijdige keten, API GET zonder call, atomic migration rollback, veilige URLs, late frontendresponse, null versus aanwezige waarden en provenance. Bestaande v1/v2/financial/CSV/rankings/monitoring-regressies blijven behouden.

Geen Product List-, GPC-, ranking- of score-integratie. Geen financiële wijzigingen, Demand Score, verkoopschatting, White Spots of scheduler. Bestaande modules voor deze bronnen zijn ongewijzigd; aparte tests vergelijken alle bestaande tabellen vóór/na metingen in testdatabases. Geen dependencies veranderd.

Beperkingen: UI haalt voorlopig alleen NL/nl op; backendcontract ondersteunt ook BE/talen. Geen automatische refresh, freshnessbeleid, scoring of primaire categorie-selectie. Twintig metingen bij readback, geen paginering van lokale historie. Proceslock is geen cross-worker lease. Veiligheidsgrenzen en bronstringredactie zijn bewust strikter dan het onbegrensde schema. Additieve gebruikersmigratie gecontroleerd toegepast, zonder bestaande gegevens te wijzigen.

Advies na de hieronder geslaagde migratiepraktijktest: gereed voor gecontroleerde commit na gebruikersgoedkeuring, zonder extra live aanvragen. De bewezen bronrespons en fixtures kunnen daarvoor worden hergebruikt in tijdelijke opslag. Daarna afronding van deze foundation; toekomstige categorie-discovery moet nieuwe expliciete contexten maken in plaats van bestaande Product List-contexten te wijzigen. Geen score- of demandkoppeling zonder afzonderlijk ontwerp.

## Bestanden

Aangepast: backend/app/core/database.py; backend/app/main.py; frontend/components/Discovery.tsx.
Nieuw: backend/app/api/placement.py; backend/app/services/placement.py; backend/tests/test_placement.py; frontend/components/ProductPlacement.tsx; frontend/tests/placement.test.cjs; docs/sprint-5.3b-product-placement.md.

Eindcontrole: exact negen bedoelde bestanden, niets staged/gecommit/gepusht; main ongewijzigd. git diff --check en whitespace van alle nieuwe bestanden geslaagd. Secretscontrole: 117 source/tracked bestanden, 0 lokale logs, 0 bevindingen. Gebruikersdatabase, .env en externe tijdelijke testhulpmiddelen/bronrespons niet in Git. Oorspronkelijke tabellen, gegevens en sequences vergeleken met eerdere geverifieerde backup; tien monitoringmeetpunten behouden, integriteit/FK goed, placementtabel additief toegevoegd tijdens de hieronder beschreven praktijktest, zonder records.

## Pre-commit migratiepraktijktest — 22 oktober 2026

Vooraf gecontroleerd: feature/bol-product-placement, main-basis 5655ac6fca55b9b0ecda19136aae4af5e609984a, exact negen bedoelde Sprint 5.3B-bestanden, geen staged wijzigingen/commits. Bestaande database aanwezig en integrity_check ok / foreign_key_check leeg. Producten 1–8, vijf discoverykandidaten en watchlistregels, één monitoringcontext en tien historische monitoringmeetpunten aanwezig.

Nieuwe SQLite online backup vóór iedere migratie, buiten de repository: `C:\Users\SCBI Zorg\.codex\.chatgpt-projects\g-p-6a65c343056c8191ac673033b6a7350a\local-backups\productradar-before-sprint53b-20261022T140738Z.db`. Backup opnieuw geopend, integriteit/foreign keys gecontroleerd en volledige schema-, record- en sequencegelijkheid met de uitgangssituatie bewezen.

De normale backendapplicatie is gestart op lokale testpoort 8774. Een uitsluitend extern testhulpmiddel blokkeerde alle BolClient-upstreamrequests; geen credentials geladen, geen live bol-calls en ook geen geblokkeerde poging. Startup voegde alleen discovery_placement_measurements, discovery_placement_ean_history en sqlite_autoindex_discovery_placement_measurements_1 toe. Geen wijziging aan bestaande tabeldefinities, records of sequences. Ranglijst-/impressionsopslag, financiële profielen en alle bol-/marktsnapshots exact intact. De nieuwe placementtabel bevat nul records.

Op de echte installatie retourneert GET /api/discovery/placement/5407012560150 items=[]. De daadwerkelijke frontendcomponent heeft die lokale read-only API geladen en toont Geen opgeslagen placementmeting. Dit is geen nieuwe bol-response en geen claim van ontbrekende webshopcategorieën. Geen fictieve of eerder tijdelijke live-resultaten in de gebruikersdatabase ingevoerd.

Volledige placementketen met uitsluitend MockTransport en tijdelijke SQLite-database: expliciete API-POST → bestaande OAuth/transport-interface met fixturecredentials → parser → append-only opslag → read-only API-GET → echte frontendcomponent. De eerder bewezen officiële live-placementresponse werd als fixture hergebruikt, zonder nieuwe live aanvraag. Beide aparte categoriehiërarchieën, alle IDs/namen en de exacte product-URL kwamen correct terug. NL/nl blijft expliciete requestcontext; officiële categoriedata/provenance en derived volledigheid/padpresentatie gescheiden.

Tijdelijke fixturegevallen: twee volledige meetpunten met verschillende UUIDs; een aparte partial-meting met ontbrekende naam; onbekende/lege waarden correct null; lege categories-array. Herhaling van dezelfde UUID gaf exact hetzelfde resultaat, zonder extra mock call of record. UUID met andere context gaf 409. Malformed response gaf 502 en 404-response bleef fout; beide sloegen niets op. Partial/empty records overschreven eerdere complete metingen niet. Vijf tijdelijke successrecords via GET teruggelezen. Frontend toonde meerdere paden, Onbekend, veilige productlink, lege status en brononderscheid correct. Dit is een component/API-integratiecontrole, geen handmatige browser-screenshottest. Tijdelijke database daarna verwijderd; echte gebruikersdatabase byte-voor-byte gelijk vóór/na de fixtureketen.

Na afloop wederom volledige backend-suite **475 geslaagd**, volledige frontend-suite **115 geslaagd**, Next.js 15.5.26 production build/typecontrole/paginageneratie **geslaagd**. Alle bestaande v1/v2/financial/CSV/rankings/monitoring-regressies behouden. Geen nieuwe score-, demand- of financiële integratie. Geen dependencies gewijzigd en geen productiecodefix nodig; uitsluitend dit rapport bijgewerkt tijdens de praktijktest.

Definitieve databasevergelijking met de nieuwe backup: alle oorspronkelijke tabeldefinities, records en sequences exact gelijk; producten 1–8, vijf watchlistkandidaten, context en tien monitoringmeetpunten intact. Ranglijst-/impressionsopslag, financiële profielen en bol-snapshots intact. Alleen de verwachte nieuwe lege placementtabel en indexen toegevoegd. integrity_check ok en foreign_key_check leeg.

Eindcontroles: git diff --check en whitespace van alle nieuwe bestanden geslaagd. Secretscontrole 117 source/tracked bestanden, nul lokale repositorylogs, nul bevindingen. .env, database, backup en externe testhulpmiddelen niet in Git. Tijdelijke validatiebackend na afloop gestopt. Nog exact negen bedoelde bestanden gewijzigd/toegevoegd; geen staging, commit, push of merge.

Advies: **Sprint 5.3B is klaar voor gecontroleerde commit** na expliciete gebruikersopdracht. De live capability blijft beperkt tot één bewezen OptiMate-aanvraag NL/nl; er zijn tijdens deze praktijktest geen extra live aanvragen, White Spots-calls of nieuwe functionaliteiten uitgevoerd.
