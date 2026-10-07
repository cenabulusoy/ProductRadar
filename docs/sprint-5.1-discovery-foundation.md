# Sprint 5.1 — Discovery Engine Foundation

Branch `feature/discovery-engine-foundation`, vanaf actuele main `8bce61c1e951aa2a113d80cac0b45b1213be0132`.

## Bestaande integratie en officiële contracten

De bestaande v10 BolClient bevat OAuth/tokenhergebruik, throttling/401-retry, catalogus, ratings en volledige NL/NEW-offerpaginering. Product lists, ranking/impressions, category placement en White Spots waren nog niet geïntegreerd. De bestaande catalogus-GPC is geen webshopcategorie/placement.

Primaire bronnen, gecontroleerd 7 oktober 2026:

- [Product List functionele documentatie](https://api.bol.com/retailer/public/Retailer-API/v10/functional/retailer-api/product-list.html): organische lijst op zoekterm/categorie, geen sponsored slots, geen verkoopvolume.
- [Officiële v10 OpenAPI-specificatie](https://api.bol.com/retailer/public/apispec/Retailer%20API%20-%20v10), via [ReDoc](https://api.bol.com/retailer/public/redoc/v10/retailer.html): POST `/retailer/products/list`, **application/json request**, application/vnd.retailer.v10+json response. searchTerm maximaal 50 tekens, categoryId maximaal 11; pagina 1–200, 50 lijstproducten/pagina. Respons heeft products, title, eans en sort. Onze begrenzing: uitsluitend pagina 1 en RELEVANCE; geen volgende pagina of automatische crawl.
- [v10 release notes](https://api.bol.com/retailer/public/Retailer-API/v10/releasenotes.html) en [Insights-demo](https://api.bol.com/retailer/public/Retailer-API/demo/v10-INSIGHTS.html): product-ranks geeft rang en impressions voor bekende EAN/date/context. Niet geïntegreerd en toegang niet bewezen; geen zelfstandig EAN-discoverymechanisme.
- [White Spots v1 beta](https://api.bol.com/retailer/public/Retailer-API/v1/functional/retailer-api/white-spots.html): wekelijkse CSV met EAN, titel, merk, categorie, potential en externe gemiddelde marktprijs. Potential is bol's modelsignaal, geen ProductRadar Opportunity Score of gemeten maandverkopen. Deze bron heeft een aparte version/interface; geen toegang aangenomen, geen export gestart en geen fake data.

## Architectuur en opslag

Additieve tabellen `discovery_candidates` (id, optionele unieke EAN, discovered_at) en `discovery_observations` (id, candidate_id FK, bron, meetmoment, fingerprint, volledige genormaliseerde evidence JSON). Index op candidate/id. Eén EAN vormt één kandidaat; meerdere zoekcontexten en enrichmentbronnen blijven append-only bewijs. Identieke evidence inclusief meetmoment is idempotent via hash/unieke sleutel. Een werkelijk nieuwe meting blijft historie. Verschillende EANs in dezelfde bol-listing worden niet stilzwijgend tot dezelfde handelsvariant samengevoegd.

Opslag gebruikt BEGIN IMMEDIATE met volledige rollback en FK-validatie. Geen product-, financiële-, bol-identiteit- of snapshottabellen worden geschreven. De discovery-evidence is een apart domein; een kandidaat is geen ProductRadar-product. Bol-product-ID, metadata, ratings, offers, contextpositie, completeness en provenance zitten in versieerbare bronpayloads met api_version; onbekende velden blijven null. Deze foundation verzamelt alleen geldige EAN-13 uit de lijst. GTIN-8/12/14 en handmatige kandidaten zonder EAN zijn nog geen importflow.

Migratie is herhaalbaar bij normale startup of expliciete discovery-opslag. Tests gebruiken tijdelijke databases. De echte lokale gebruikersdatabase is in deze sprint **niet gemigreerd**, de normale backend is daarop niet gestart. Bestaande acht producten, alle overige tabellen en sequences zijn read-only gelijk bevonden aan de eerdere gevalideerde uitgangssituatie.

## Provider en provenance

Product List-adapter hergebruikt exact dezelfde BolClient-instance, tokenlock, veilige transport/_check, rate-limit backoff, 401-retry en tekstredactie. Geen tweede OAuth-implementatie, geen tweede token of breder crawlerproces. POST op bol Product List is semantisch read-only. De server normaliseert/allowlist de lijst; browser mag geen officiële kandidaatdata injecteren.

Expliciete meting van één geselecteerde kandidaat hergebruikt BolClient.preview. Catalogus/ratings/offers worden in discovery-evidence opgeslagen zonder bestaande product/snapshotdata te muteren. Mislukte aanvraag wordt een derived error-marker; oudere complete meting blijft historie en wordt nooit huidige fallback. Marktclassificatie gebruikt ongewijzigd services.freshness.classify: ≤24 uur current, >24–72 stale, >72 historical, anders missing/incomplete/error. Dezelfde financiële veiligheidsgrens blijft bestaan. Discovery observation-ID wordt als referentie gebruikt; het is geen bestaande bol-snapshot-ID.

Officieel gemeten: EAN/titel uit lijst, catalogus, ratingverdeling, offerprijzen/metadata. Derived: contextpositie in een RELEVANCE-lijst, ratinggemiddelde/-totaal, aanbod-/verkoperstellingen, freshness en bewijsdekking. De ingevoerde zoekcontext wordt bewaard; GPC en zoekcategorie blijven gescheiden. Estimated is een ondersteunde provenancecategorie, maar deze sprint produceert **geen** geschatte verkopen, vraagranges of confidence voor een sales estimator. Ranking/impressions, ratinggroei, sales_volume en White Spots blijven null. Er worden geen schattingen in productvelden gekopieerd.

## Transparante onderzoekslabels, geen Opportunity Score

Vraag: lijstzichtbaarheid en ratings (geen verkoopbewijs). Concurrentie: aantal aanbiedingen en unieke retailers afzonderlijk. Marktprijs: volledige officiële offers, relevante prijs/min/max en fulfilment/leverinformatie. Bewijskwaliteit: expliciete coverage en freshness.

Coverage maximaal 100: 20 per beschikbaar identifier, catalogustitel, ratings, actuele complete markt en lijstzichtbaarheid. Catalogus/ratings/lijstzichtbaarheid hebben freshnessgewicht 1 bij ≤24h, 0,5 bij >24–72h en 0,25 bij >72h. Identifier is stabiel; markt telt alleen als huidige bruikbare meting. Dit is **dekking**, geen betrouwbaarheid van commercieel succes, Opportunity Score of verkoopkans. Nul ratings is aanwezige informatie maar geen positieve vraag.

Labelprioriteit:
1. Hoge concurrentie: actuele complete markt en ≥20 unieke verkopers.
2. Interessant signaal: actuele lijstzichtbaarheid en markt, ratingsgemiddelde ≥4 bij ≥10 ratings. Betekent onderzoekskandidaat; vraag/financiën niet bewezen.
3. Verder onderzoeken: lijstzichtbaarheid of actuele markt aanwezig.
4. Onvoldoende bewijs: geen van beide.

Elke respons geeft reasons, missing, signal_groups en provenance. Opportunity Score blijft altijd null. Labeldrempels zijn expliciete onderzoeksheuristieken, geen wijziging aan Decision v2-beleid. Lage concurrentie alleen geeft geen positief label. Historische zichtbaarheid kan verder onderzoek rechtvaardigen, maar blijft voorzien van meetmoment en lagere dekking.

## API en UI

- GET `/api/discovery/capabilities`: integratiestatus; geen live check en geen beweerde toegang.
- POST `/api/discovery/collect`: expliciete zoekterm/categorie, maximaal één pagina; schrijft uitsluitend discovery-evidence.
- GET `/api/discovery/candidates`: filters categorie/bron/freshness/max verkopers/prijsrange/min dekking; sort discovered/quality/sellers; pagina-offset/limit.
- GET `/api/discovery/candidates/{id}`: details, bewijs, ontbrekende inputs, markt/historie.
- POST `/api/discovery/candidates/{id}/measure`: expliciete catalogus/ratings/offermeting van één EAN, behoud historie.
- GET `/api/discovery/candidates/{id}/promotion-preview`: read-only voorstellen, bestaande product-ID's met dezelfde EAN, altijd can_promote false/writes_products false.

Alle responses no-store. Collect/measure hebben één proceslock en UI duplicate-click guard; SQLite deduplicatie geldt ook bij concurrente databasewrites. Geen scheduler. De proceslock is geen cross-worker upstream-lease; daarvoor is later een aparte begrensde discovery-jobarchitectuur nodig.

Nieuwe route `/discovery`, navigatielink naast Product Hunter. Overzicht, expliciete collect-knop, filters/sortering/paginering, detail, afzonderlijke meetknop en promotiepreview. Onbekend is geen nul. Actuele prijs uitsluitend bij central current; historie expliciet context. Een mislukte nieuwe meting toont geen oude actuele prijs. Provenancelegend, bron/datums, GPC/zoekcategorie, marktgegevens/fulfilment en “Nog geen inkoopadvies — financiële gegevens ontbreken” zijn zichtbaar. Geen dashboardmigratie.

## Live capability-check

De eerste begrensde check na offline tests/build gaf OAuth 200 en Product List 415. Het demo-media type verschilde van de officiële OpenAPI-specificatie; daarna is het request gecorrigeerd naar application/json en offline getest.

Op afzonderlijk expliciet gebruikersverzoek is vervolgens de pre-commit capabilityvalidatie uitgevoerd: **exact één** nieuwe live Product List-aanvraag met zoekterm WD-40 Smart Straw 400 ml, NL/RELEVANCE/pagina 1, application/json request en v10 vendor-JSON Accept. OAuth **200**, Product List **200**. Accounttoegang voor deze aanvraag is bewezen. Respons: 6 lijstproducten, 10 unieke geldige EANs (alle 10 nog onbekend in bestaande products), root products/sort, per product uitsluitend title/eans, per EAN uitsluitend ean. Geen product-ID, merk, categorie/placement, prijzen, ratings, verkopers, impressions of verkoopvolume in deze response. Sort RELEVANCE; parser complete, 0 ongeldige entries; geen parser-/contractfix nodig.

Maximaal drie geparste kandidaten zijn in een nieuwe tijdelijke database opgeslagen, herhaald en gedupliceerd aangeleverd: precies drie kandidaten met ieder één evidence-observation. Titel/EAN official_measured, lijstpositie derived; markt en sales onbekend, Opportunity Score null. Bestaande overzichts-API en frontend-overzicht/detail zijn gecontroleerd met dezelfde genormaliseerde live resultaten, uitsluitend lokale/gemockte GETs. Geen candidate enrichment, White Spots of extra Product List-call. Windows hield het testbestand aanvankelijk open; na procesafsluiting is uitsluitend de tijdelijke database en lege testmap verwijderd. Geen productiecodefix nodig; alleen dit rapport bijgewerkt. Gebruikersdatabasehash en alle tabelrijen vóór/na exact gelijk, geen echte discoveryrecords of migratie geschreven. Credentials/tokens nooit getoond of gelogd.

## Validatie en behoud

Volledige backend-suite: **351 geslaagd** (324 bestaande + 27 nieuwe). Volledige frontend-suite: **85 geslaagd** (79 bestaande + 6 nieuwe). Definitieve Next.js 15.5.26 production build inclusief typecontrole en paginageneratie: **geslaagd**. Git diff --check plus whitespacecontrole van nieuwe bestanden: **geslaagd**. Secretscontrole: **98 bestanden, 0 lokale logs, 0 bevindingen**; .env blijft genegeerd. Database-inhoud/schema/sequences read-only exact gelijk aan gevalideerde uitgangssituatie; integrity_check ok, foreign_key_check leeg. Nieuwe tests dekken dedup/meerdere bronnen/atomiciteit/concurrent writes/provenance/null-versus-nul/geen sales of score/onvolledige responses/24h-72h/failure zonder fallback/filter-sort/context-EANs/HTTP415-contract/rate-limits/White Spots-interface/promotiepreview/geen productmutaties.

Pure v1, Financial v2, Decision v2 en policy, centrale freshness, bestaande bol-client, offers, snapshots, market refresh, financial profiles, CSV en dependencybestanden blijven byte-identiek aan main. Bestaande regressietests blijven behouden. Secrets-/diffcontrole worden na documentatie uitgevoerd. Geen commit, push of merge.

## Beperkingen en Sprint 5.2

De foundation kan voor deze account **aantoonbaar nieuwe EAN-kandidaten ontdekken** via een expliciete Product List-zoekactie; de pre-commitcheck gaf 10 nog onbekende EANs. Dit gaat verder dan bekende EAN-analyse, maar is geen autonome scheduler/crawl of bewijs van commerciële haalbaarheid. Toegang is voor deze ene NL/RELEVANCE-zoekcontext bewezen, niet voor elke categorie of ieder ander endpoint. Sprint 5.2 kan begrensde jobs/leases, categorieverkenning en expliciete enrichmentvalidatie toevoegen. Product List heeft directe waarde als officiële EAN-discoverybron; White Spots blijft aanvullende beta bron met onbewezen toegang. Een marketing/affiliate Catalog API vereist afzonderlijke toegangs- en licentiecontrole voordat die alternatief wordt.

Geen brede ranking-, placement- of White Spots-crawl, geen echte gebruikersmigratie, geen sales estimator, geen ratinggroei zonder meetreeks, geen financiële score/inkoopadvies en geen daadwerkelijke promotie. Collectie is gebruiker-geïnitieerd; geen autonome scheduler. Volgende sprint kan gecontroleerde capabilityverificatie, begrensde job/lease, placement/rank-context en herhaalde ratingsmeting toevoegen, zonder v2-productiebeleid te wijzigen.

## Bestanden

Nieuw: backend/app/api/discovery.py; backend/app/services/discovery.py; backend/app/services/discovery_provider.py; backend/tests/test_discovery.py; frontend/app/discovery/page.tsx; frontend/components/Discovery.tsx; frontend/tests/discovery.test.cjs; dit rapport.

Aangepast: backend/app/core/database.py; backend/app/main.py; frontend/app/layout.tsx. Geen dependencywijzigingen.
