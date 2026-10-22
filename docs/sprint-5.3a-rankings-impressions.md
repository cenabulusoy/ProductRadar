# Sprint 5.3A — Rankings & Impressions Foundation

Branch: `feature/bol-rankings-impressions`, gebaseerd op main `c110a0d1b70f23fe01523eb851cbae7fd35328c3`. Geen commits, push, merge, scheduler, White Spots- of placementcalls. Geen wijziging aan Product List-posities, v1/v2, financiële profielen of scorebeleid.

## Gecontroleerd v10-contract

Bronnen, geraadpleegd 22 oktober 2026:

- [Functionele documentatie](https://api.bol.com/retailer/public/Retailer-API/v10/functional/retailer-api/product-rankings-and-impressions.html)
- [Officiële OpenAPI](https://api.bol.com/retailer/public/apispec/Retailer%20API%20-%20v10), operationId `get-product-ranks`, schemas `ProductRanks` en `Rank`.
- [Gepubliceerde rate limits](https://api.bol.com/retailer/public/ratelimits) en [conventies](https://api.bol.com/retailer/public/Retailer-API/conventions.html).

GET `https://api.bol.com/retailer/insights/product-ranks`, zonder requestbody. Verplichte queryparameters: `ean` en `date` (YYYY-MM-DD). Optioneel `type`: SEARCH/BROWSE; we laten het weg voor beide contexten. Geen letterlijke null-string, want deze staat niet in het OpenAPI-enum. `page` 1–200, default 1, 50 items/pagina. Deze foundation ondersteunt uitsluitend pagina 1 en doet nooit automatisch een vervolgaanvraag. Headers: Bearer-token via bestaande OAuth-client, Accept application/vnd.retailer.v10+json, Accept-Language nl-NL (officieel toegestaan).

Datum: drie kalendermaanden terug tot en met gisteren. Backend rekent in Europe/Amsterdam met expliciete kalendermaandgrens en eindemaandcorrectie. `tzdata==2026.5` toegevoegd omdat Windows hier geen IANA-zonegegevens had. Bestaande dependencies niet geüpgraded. Datumvalidatie gebeurt vóór OAuth/upstreamverkeer.

Belangrijk: het endpoint heeft **geen country/country-code parameter of country-responseveld**. `country` is lokaal null met uitleg; nl-NL is een taalkeuze en geen gemeten NL-landfilter. Geen fictieve landdekking.

Response-object verplicht `ranks` (array) en `hasNextPage` (boolean). Elk Rank-object verplicht `rank` (int32), `impressions` (int32), `wasSponsored` (boolean). `categoryId` en `searchTerm` zijn optioneel/nullable strings. Geen EAN, datum, land of expliciet SEARCH/BROWSE-type per record in dit schema. Queryidentiteit wordt afzonderlijk bewaard. Rank 0 wordt behouden omdat het schema geen minimum specificeert; de adapter weigert negatieve rank/impressions als onbruikbare waarden. Ontbrekende verplichte getallen of bool geven een contractfout, nooit een fictieve nul of organic-status.

Officiële veldwaarden staan in `records[].official`. Alleen contextinferentie staat in `records[].derived`: alleen zoekterm → SEARCH; alleen categorie → BROWSE; beide/geen → null. Het requesttype wordt los bewaard en niet als gemeten recordtype gepresenteerd. `wasSponsored=false` wordt 'Niet gesponsord', true 'Gesponsord'. Impressions zijn viewable impressions, geen clicks, vraag of verkopen. Volgens de functionele bron: minstens één seconde en voor 50% in beeld.

Completeness wordt apart afgeleid: hasNextPage=true → partial en all_pages_retrieved=false; anders complete binnen de geselecteerde query. Een complete lege lijst bewijst geen nul zichtbaarheid. Geen totalen, CTR, verkoopaantallen of globale rank verzonnen.

Rate limit op deze route volgens de gepubliceerde lijst: 10 GET/s. Limieten kunnen veranderen; 429 en Retry-After gaan via bestaande BolClient-backoff. Voor deze sprint één rankingaanvraag per expliciete actie. Geen automatische retry, ook niet bij 401, zodat een capabilityfout niet ongemerkt een tweede live rankingpoging veroorzaakt. Bestaande `_get`/401-logica van andere integraties blijft intact.

OpenAPI route noemt 200, 400 en 406. Daarnaast blijven algemene OAuth/toegang 401/403, 404, 415, 429 en 5xx/netwerkfouten mogelijk; bestaande veilige foutvertaling wordt hergebruikt. Geen upstreambody, authheaders of credentials in API-fouten/logs. Een lege 200 is geaccepteerde toegang, geen weigeringsbewijs. Accountrechten voor andere EANs/data/contexten zijn niet afgeleid uit deze ene proef.

## Architectuur, opslag en API

`rankings.fetch` hergebruikt dezelfde BolClient/token/transport/backoff en bestaande tekstredactie. Er is geen tweede OAuth-client. Strikte, allowlisted parser met maximaal 50 records; onverwachte extra velden worden niet aan frontend of opslag doorgegeven. Bronstrings zijn veilig geredigeerd en begrensd via bestaande `_text`.

Eén additieve tabel `discovery_ranking_measurements`: id, unieke request_id, query_key, unieke fingerprint, EAN, verslagdatum, retrieved_at en veilige payload. Index discovery_ranking_ean_date. Payload bewaart officiële records, gevraagde context/taal, onbekend land, provenance/API-versie, paging en derived completeness. Geslaagde lege resultaten zijn ook bewijs van de uitgevoerde query en worden als leeg opgeslagen. Fouten worden niet als lege succesvolle meting opgeslagen.

Migratie is herhaalbaar en neemt deel aan de normale startuptransactie. Er zijn geen ALTER/UPDATE/DELETE-acties op bestaande product-/snapshot-/profiel-/monitoringtabellen. De naamruimte discovery_* houdt de afzonderlijke bron gescheiden van bestaande bol-snapshotstructuren en hun rollbackcontracten. Bestaande snapshot-regressietests blijven ongewijzigd.

UUID-herhaling retourneert de opgeslagen succesvolle response zonder extra upstreamcall; UUID met andere query geeft 409. Een identieke payload onder een nieuwe UUID wordt via fingerprint één meetpunt, met behoud van het eerste retrieved_at (er kan dan wel een expliciete nieuwe upstreamaanvraag zijn). Binnen één backendproces blokkeert een lock gelijktijdige rankingketens met 409. Dit is geen multiworker/joblease; uitbreiding daarvoor hoort bij eventuele latere monitoring. Geen automatische fallback of veldoverschrijving.

- GET `/api/discovery/rankings/{ean}`: maximaal 20 opgeslagen metingen plus serverberekende latest_allowed_date; geen live call of migratie.
- POST `/api/discovery/rankings`: expliciete actie met ean, report_date, nullable context_type, request_id UUID. Geen caller-injected records/pagina/land toegestaan. Slaat uitsluitend nieuwe afzonderlijke rankingmeting op.

Response bevat id, ean, report_date, retrieved_at, country=null/reason, language, requested_type, page, has_next_page, status, records, http_status, provenance, completeness en zichtbaarheidnotice. APIs no-store. Frontend leest opgeslagen gegevens bij openen; expliciete knop voor één nieuwe pagina. Onzeker netwerkresultaat behoudt UUID, dubbele klikken geblokkeerd, wisselen van kandidaat kan geen late oude respons tonen. Geen automatische calls bij datum-/contextkeuze.

## Eén live capability-check — 22 oktober 2026

Pas na 43 geslaagde offline contracttests uitgevoerd. EAN 5407012560150; verslagdatum gisteren in Nederlandse tijd: **2026-10-21**; type weggelaten (beide), pagina 1, taal nl-NL.

- OAuth HTTP 200.
- Exact één ranking GET, HTTP 200.
- Rootvelden daadwerkelijk aanwezig: ranks, hasNextPage.
- ranks=[]: **0 records**; hasNextPage=false.
- Geen recordvelden daadwerkelijk observeerbaar: rank, impressions, sponsored en contextvormen zijn nog uitsluitend via officiële schema’s en fixtures gevalideerd.
- Accounttoegang voor deze aanvraag bevestigd; lege lijst is geen contract- of autorisatiefout en geen bewijs van nul impressions/verkoop.
- Parser accepteerde de response zonder contractafwijking. Geen vervolgpagina, retry, enrichment, placement of White Spots-call.
- retrieved_at: **2026-10-22T13:25:48.710818+00:00**.
- Opslag/readback gecontroleerd in een tijdelijke SQLite-database, daarna verwijderd. De echte gebruikersdatabase is vóór/na cryptografisch exact gelijk; de nieuwe migratie is daarop nog niet toegepast.

De bestaande tien monitoringmeetpunten en oorspronkelijke gebruikersgegevens blijven behouden. Het lege live testresultaat is bewust niet in de gebruikersdatabase overgenomen. De UI kan lege officiële responses correct uitleggen en echte niet-lege responses via fixtures tonen; er zijn geen fictieve records toegevoegd.

## Beperkingen en vervolgadvies

Nog geen bewijs dat dit account voor OptiMate bruikbare rankingrecords krijgt op andere dagen, of dat andere EANs/contexten gegevens geven. Geen product-landfilter; geen koppeling aan auto-onderhoud-Product List-posities. Geen impact op bewijsdekking, discoverylabels of engines. Eén pagina, max. 20 lokale metingen bij readback; geen scheduler, reeksaggregatie, verkoopschatting, Demand Score of automatische refresh. Geen cross-worker leasegarantie.

Kleinste vervolg: afzonderlijk geautoriseerde capabilityproef voor één andere bekende EAN of één andere toegestane verslagdatum, wederom één pagina. Eerst een daadwerkelijk niet-leeg bronrecord en contextsemantiek bevestigen voordat deze bron in historische monitoring of prioritering wordt opgenomen. Geen volumeschatting op basis van impressions alleen.

## Definitieve validatie

- Volledige backend-suite: **434 tests geslaagd** (387 bestaande + 47 nieuwe).
- Volledige frontend-suite: **105 tests geslaagd** (97 bestaande + 8 nieuwe).
- Next.js 15.5.26 production build, typecontrole en alle pagina's: **geslaagd**.
- Bestaande snapshotrollbacktest bleef behouden; de nieuwe bron gebruikt discovery_*-namespace. Eigen rollbacktest bevestigt transactionele additieve migratie.
- Requirements behoudt de bestaande UTF-16-encoding; uitsluitend tzdata==2026.5 toegevoegd. Geen andere versies gewijzigd.
- Gewijzigd: backend/app/core/database.py; backend/app/main.py; backend/requirements.txt; frontend/components/Discovery.tsx.
- Nieuw: backend/app/api/rankings.py; backend/app/services/rankings.py; backend/tests/test_rankings.py; frontend/components/RankingVisibility.tsx; frontend/tests/rankings.test.cjs; dit rapport.

Laatste controles: git diff --check en whitespace van alle nieuwe bestanden geslaagd; secretscontrole 111 source/tracked bestanden, 0 lokale logs, 0 bevindingen. Exact 10 bedoelde bestanden, niets staged/gecommit/gepusht. Gebruikersdatabase en .env genegeerd; live testopslag en tijdelijke hulpmiddelen buiten Git. Branchbasis en main ongewijzigd.

## Aanvullende geautoriseerde capability-test — 22 oktober 2026

Op expliciet gebruikersverzoek één aanvullende test, geen derde poging: EAN 6090314188178 (remmenreiniger), verslagdatum 2026-10-21, type weggelaten, pagina 1. Checksum EAN-13 en verslagdatum vóór OAuth gevalideerd. De datum valt binnen drie kalendermaanden en uiterlijk gisteren in Europe/Amsterdam.

OAuth HTTP 200 en exact één ranking GET HTTP 200. Rootvelden ranks en hasNextPage; ranks=[] (0 records), hasNextPage=false. Complete lege respons voor deze aanvraag, zonder contractafwijking of vervolgpagina. Geen recordvelden waargenomen: rank, impressions, wasSponsored, searchTerm en categoryId blijven voor echte records onbevestigd. Geen conclusie van nul zichtbaarheid of ontbrekende accounttoegang.

De bestaande parser accepteerde de respons. Officiële queryrespons/provenance en afgeleide completeness bleven gescheiden; bij nul records is geen per-record contextinferentie te valideren. retrieved_at 2026-10-22T13:35:18.857371+00:00. Tijdelijke SQLite-opslag, service-readback en GET /api/discovery/rankings/6090314188178 gaven exact dezelfde meting terug. Geen live calls bij GET. Tijdelijke database daarna verwijderd. De echte gebruikersdatabase was cryptografisch gelijk vóór/na; alle tien bestaande monitoringmeetpunten behouden, integrity_check ok, foreign_key_check leeg. Geen echte rankingsmigratie toegepast.

Geen Product List, catalogus/ratings/offers, placement, White Spots of andere geauthenticeerde endpointcalls. Geen productiecodefix nodig. Beide geautoriseerde capabilityproeven leverden een geldige lege respons op; niet-lege recordsemantiek blijft alleen door contractfixtures getest. De beperkte foundation is gereed voor een gecontroleerde pre-commit migratiepraktijktest na een nieuwe backup. Dit is geen bewijs dat de bron al bruikbare zichtbaarheidssignalen voor onze kandidaten levert. Die beperking moet bij definitieve afronding expliciet behouden blijven; geen verdere live poging automatisch uitvoeren.

## Pre-commit migratiepraktijktest — 22 oktober 2026

Branch feature/bol-rankings-impressions, HEAD/main-basis c110a0d1b70f23fe01523eb851cbae7fd35328c3. Vooraf exact de tien bedoelde bestanden, geen staged wijzigingen/nieuwe commits en geen wijzigingen aan engines, financiële profielen of bestaande discovery-/monitoringlogica.

Nieuwe geverifieerde SQLite online backup buiten de repository: `C:\Users\SCBI Zorg\.codex\.chatgpt-projects\g-p-6a65c343056c8191ac673033b6a7350a\local-backups\productradar-before-sprint53a-20261022T133854Z.db`. Vooraf integrity_check ok en foreign_key_check leeg; backup volledig gelijk aan uitgangsdatabase. Aanwezig: oorspronkelijke producten 1–8, tien echte monitoringmeetpunten, vijf watchlistkandidaten en één opgeslagen monitoringcontext.

De normale backendapplicatie is gestart op een lokale testpoort, met externe blokkade op alle BolClient-upstreamrequests. Geen credentials geladen en geen enkele live bol-call of geblokkeerde poging. Startup heeft uitsluitend discovery_ranking_measurements, discovery_ranking_ean_date en de twee bijbehorende automatische unique-indexes toegevoegd. Alle oorspronkelijke tabeldefinities, records en sequences zijn vóór/na exact gelijk. De echte rankingtabel blijft leeg; geen fictieve of eerdere capability-testresultaten geïmporteerd.

De read-only API op de echte installatie retourneert items=[] en latest_allowed_date=2026-10-21. De daadwerkelijke frontendcomponent heeft deze lokale API via uitsluitend GET geladen en toont geen opgeslagen rankingmeting. Niet verwarren met een uitgevoerde bol-query met nul records: zonder opgeslagen meting zijn bronwaarden onbekend.

De volledige meetketen is daarnaast uitsluitend met MockTransport-fixtures in een tijdelijke database getest: API → bestaande OAuth/transport-interface met fixturecredentials → parser → opslag → read-only API → frontendcomponent. Geen geauthenticeerde netwerkrequests. Gevalideerd: complete lege response; niet-lege records met rank 1/4/0, impressions 0/23/0, false/true sponsored, SEARCH/BROWSE en onbekende context; ontbrekende optionele categorie/zoekterm; hasNextPage=true met partial-status en zonder vervolgrequest; ontbrekende verplichte rank geeft 502 en slaat niets op. Officiële bronwaarden blijven in official, contextinferentie in derived. Land blijft null/onbekend: geen bevestigde NL-ranking op basis van taal. Geen vraag- of verkoopclaim.

UUID-herhaling retourneert identiek opgeslagen resultaat zonder extra mock rankingcall. Een incomplete nieuwe response wordt afzonderlijk toegevoegd en behoudt oude complete/lege resultaten; foutieve response overschrijft niets. Alle fixtures zijn uit de tijdelijke database via GET teruggelezen en door de echte React-component weergegeven. Dit is een component/API-integratiecontrole, geen handmatige browser-screenshottest. Tijdelijke testdatabase verwijderd. Een Windows-testhandle vereiste garbage collection in uitsluitend het externe testhulpmiddel voor cleanup; geen productiecodefix nodig en geen gebruikersdata geraakt.

Na afloop opnieuw volledige backend-suite 434 geslaagd, frontend-suite 105 geslaagd, Next.js 15.5.26 production build/typecontrole/paginageneratie geslaagd. Database-integriteit ok en foreign keys foutloos. Vergelijking met de nieuwe backup bevestigt alle bestaande gegevens intact, inclusief de tien meetpunten, vijf watchlistregels en context. Ranglijsttabel leeg. Geen automatische score-integratie; beschermde engine-/financial-/discoverymodules ongewijzigd en bestaande regressies geslaagd. Alleen dit rapport inhoudelijk bijgewerkt voor de praktijktest; geen broncodefixes.

Eindcontroles: git diff --check en whitespace geslaagd, secretscontrole 111 source/tracked bestanden, 0 lokale logs, 0 bevindingen. Geen database, backup, .env of tijdelijke hulpmiddelen in Git. De tijdelijke backend voor validatie wordt na de checks gestopt. Tien bedoelde bestanden blijven ongecommit; geen push of merge.

Advies: gereed voor gecontroleerde commit na gebruikersgoedkeuring. **Echte niet-lege rankingrecords zijn nog niet live aangetoond.** Twee afzonderlijk geautoriseerde capabilityproeven leverden correcte lege responses; de migratiepraktijktest verandert die beperking niet. Geen extra live pogingen uitgevoerd.
