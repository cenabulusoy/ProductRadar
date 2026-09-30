# Sprint 3.3 — Market Intelligence

## Contract en scope

Officiële bronnen, gecontroleerd tijdens implementatie:

- [Competing Offers v10](https://api.bol.com/retailer/public/Retailer-API/v10/functional/retailer-api/competing-offers-api.html)
- [Retailer API v10-contract](https://api.bol.com/retailer/public/redoc/v10/retailer.html)
- [Officiële productdemo's](https://api.bol.com/retailer/public/Retailer-API/demo/v10-PRODUCTS.html)

De bestaande EAN-preview haalt nu ook `GET /retailer/products/{ean}/offers` op met `country-code=NL`, `condition=NEW`, `best-offer-only=false` en oplopende `page`. Het contract gebruikt 50 items per pagina en maximaal pagina 200. Na een korte/lege pagina stopt ophalen. Een volle laatste toegestane pagina wordt onvolledig verklaard. Er worden geen willekeurige upstream-links gevolgd. OAuth-hergebruik, één herauthenticatie bij 401, timeouts en 429-cooldown blijven gedeeld met catalogus/ratings.

Bol levert offer-ID, retailer-ID, aanbiedingsprijs, beste-aanbiedingmarkering, fulfilment, conditie, land, uiterste besteltijd en leverdatums. Niet ieder optioneel veld hoeft beschikbaar te zijn. `bestOffer` is een bol-selectie, geen synoniem voor goedkoopste. De interface gebruikt EUR voor de huidige NL-scope; er worden geen verzendkosten, ledenkortingen of andere niet-geretourneerde prijscomponenten geschat.

## Dataverwerking

`market.py` valideert de responsschema's en bewaart alleen geselecteerde, geschoonde velden. De bronmetadata bevat API-versie, endpoint, NL/NEW, begin-/eindtijd, paginaresultaten en veilige foutcodes. Codes bij mislukte pagina's zijn adaptercodes, niet noodzakelijk de oorspronkelijke upstream-HTTP-status.

- Officiële bol-data: aanbiedingen, prijzen, retailer-ID's, beste-aanbiedingmarkering en lever-/fulfilmentmetadata.
- Afgeleid door ProductRadar: aantal aanbiedingen, aantal unieke retailer-ID's, minimum/maximumprijs en laagste aanbieding. Retailer-ID `0` telt mee; meerdere aanbiedingen van dezelfde retailer verhogen niet het aantal unieke verkopers.
- Geen schattingen van verkoopvolume. Geen wijzigingen aan handmatige `sale_price`, `purchase_price`, verzendkosten, CSV-data, Opportunity Score of Decision Engine.

Een expliciete geldige lege lijst op een afgeronde paginering mag nul ontvangen aanbiedingen/verkopers opleveren. Een ontbrekende lijst, 404, ongeldige kernvelden, verkeerde land-/conditiefiltering, overlappende offer-ID's of mislukte vervolgpaginering levert geen totale nulwaarden op: de totalen, prijsrange en definitieve laagste/beste selecties zijn dan null. Wel ontvangen aanbiedingen en waargenomen tellingen blijven beschikbaar, duidelijk als onvolledige waarneming. Identieke offer-ID's worden niet dubbel geteld; een herhaalde pagina zonder nieuwe aanbiedingen stopt de lus. Niet-beschikbare optionele fulfilment-/levermetadata blijft null.

`complete` betekent alle relevante pagina's binnen het contract opgehaald en kernvelden geldig, geen garantie dat een bewegende markt atomair is gemeten. `partial` bevat bruikbare waarnemingen met onvolledigheid; `unavailable` bevat geen bruikbare aanbiedingen na een fout. De bovenliggende preview wordt gedeeltelijk wanneer marktdata of ratings niet volledig zijn. Catalogusfouten blijven een fout op de preview geven.

## Additieve opslag

De bestaande snapshot-JSON krijgt een optioneel `market`-veld. Oude snapshots worden niet aangepast en blijven leesbaar; de interface toont dat er toen geen marktmeting opgeslagen is.

Nieuwe tabel `bol_market_snapshots`:

- `snapshot_id`: primaire sleutel en foreign key naar de product-snapshot;
- `ean`: foreign key naar de bol-identiteit;
- `measured_at`, `source`, `api_version`, `country`, `condition`, `status`;
- `payload`: volledige geschoonde marktmeting met offermetadata, paginaresultaten en afgeleide tellingen.

Een index ondersteunt zoeken op EAN/land/conditie/meetmoment. De bestaande transactie maakt identiteit, product-snapshot en marktmeting samen aan. Een mislukte marktinsert rolt alles terug. De bestaande unieke previewreferentie maakt opnieuw of gelijktijdig opslaan idempotent. Een nieuwe preview is een nieuw meetmoment en mag een nieuwe historische snapshot opleveren, ook bij gelijke prijzen. De expliciete opslagactie haalt niets opnieuw bij bol op en accepteert geen marktvelden van de browser.

De migratie gebruikt `CREATE TABLE/INDEX IF NOT EXISTS` binnen de bestaande startuptransactie; bestaande tabellen/rijen veranderen niet. Tests dekken oude snapshots, herhaling en rollback. De lokale gebruikersdatabase is tijdens deze sprint niet gemigreerd: de nieuwe tabel wordt bij de volgende backendstart aangemaakt. Geen testrecords achtergelaten. Voor een downgrade kunnen de additieve tabel en index blijven bestaan; eerdere versies schrijven dan snapshots zonder marktmeting.

## Interface en grenzen

Marktgegevens verschijnen in de EAN-preview én de opgeslagen snapshot. De interface onderscheidt prijsrange, laagste aanbieding, bol-beste aanbiedingen, unieke verkopers en aantal aanbiedingen, met bron/meetmoment en ouderdom bij weergave. De uitklaplijst toont de eerste 50 ontvangen aanbiedingen; de volledige meting wordt opgeslagen. Onvolledige waarnemingen worden niet als totale marktgetallen weergegeven. Er is geen automatische prijs- of score-integratie.

Alle aanvragen lopen opeenvolgend; er is geen atomaire bol-marktsnapshot over meerdere pagina's. Marktbeweging tijdens ophalen kan niet volledig worden uitgesloten. Maximaal 200 pagina's, geen achtergrondverversing of automatische retries na rate limiting. De bestaande lokale één-proces-previewcache (15 minuten, maximaal 256 previews) blijft van toepassing. Geen live stress-, multipagina- of rate-limittest: die scenario's zijn met mocks getest.

## Validatie

Mocktests omvatten paginering, gedeelde retailer-ID's, `0` als retailer-ID, laagste versus beste prijs, lege/ontbrekende data, foutieve kernvelden, metadata, foutieve JSON, timeouts, rate limiting, overlappende/herhaalde pagina's, paginalimiet, oude snapshots, transactierollback en idempotente opslag. Bestaande CSV-, product- en score-regressietests blijven behouden. Frontendtests dekken dezelfde semantische verschillen, bronvermelding, ouderdom, veilige tekstweergave en expliciet opslaan.

Beperkte live read-only controles na geslaagde mocktests en build zijn geslaagd, voor zowel een lege als een niet-lege aanbiedingenrespons. Geen live snapshot opgeslagen. Databasebytes, productrecords en berekende scores bleven exact gelijk. Concrete live meetwaarden en responsegegevens worden niet in de repository bewaard. Geen credentials/tokens gelogd of opgeslagen.
