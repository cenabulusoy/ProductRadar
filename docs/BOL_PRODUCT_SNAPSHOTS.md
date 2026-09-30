# Sprint 3.2 — Product Identity & Snapshots

## Datagrens

`products` blijft de bestaande handmatige/CSV-dataset voor de Decision Engine. Geen snapshotendpoint schrijft naar deze tabel of naar scores. EAN is de logische koppeling, geen automatische import of synchronisatie. Eén bol-identiteit per EAN, ook bij herhaald of gelijktijdig ophalen. Een eventueel aangeleverd `productId` wordt als bol-product-ID bewaard; ontbreekt dit, dan blijft het null. EAN wordt nooit als bol-product-ID verzonnen. Verschillende EANs worden niet op basis van een vermoede product-ID samengevoegd.

Alleen geselecteerde en geschoonde catalogusmetadata en de sterrenverdeling worden opgeslagen. Ruwe bol-responses, OAuth-tokens en credentials worden niet opgeslagen. `data_kinds` onderscheidt officiële catalogusdata/sterrenverdeling van het door ProductRadar berekende ratingaantal en gemiddelde. Handmatige prijzen en geschatte verkoopaantallen horen niet bij deze bronmetingen.

## Tabellen en migratie

- `bol_product_identities`: EAN als primaire sleutel, optionele bol-product-ID, aanmaaktijd. Een ontbrekende ID kan later worden ingevuld; een afwijkende ID overschrijft een bestaande identiteit niet, maar blijft zichtbaar in de betreffende snapshot.
- `bol_product_snapshots`: uniek snapshot-ID en preview-ID, EAN foreign key, UTC-meetmoment en opslagtijd, bron, API-versie, volledigheidsstatus en JSON-payload. Index op EAN/meetmoment. De payload bevat de metadata, ratings, waarschuwingen, veldbeschikbaarheid en endpointstatussen.

Startup voert een additieve SQLite-migratie uit in een expliciete transactie. `CREATE TABLE/INDEX IF NOT EXISTS` maakt herhalen veilig. Bestaande tabellen en rijen worden niet aangepast of verwijderd; foreign keys worden per verbinding ingeschakeld. Een fout rolt de migratietransactie terug. De migratie is getest op een legacy-schema met bestaande producten; de bestaande lokale database wordt pas bij de volgende app-start gemigreerd. Maak zoals gebruikelijk vóór deployment een databaseback-up. De vorige app-versie kan met de uitgebreidere database blijven werken; verwijder de nieuwe tabellen niet bij rollback.

## API en expliciet opslaan

- `GET /api/bol/ean-preview/{ean}` blijft database-read-only. Het antwoord bevat nu ook een willekeurige `preview_id`, optionele product-ID, endpointversies/statussen, veldbeschikbaarheid en dataclassificatie.
- `POST /api/bol/snapshots` accepteert uitsluitend `{ "preview_id": "..." }`. Geen door de browser aangeleverde productvelden: de backend bewaart exact zijn eigen geschoonde preview, zonder nieuwe bol-aanvraag. Opslaan is atomair. Dezelfde preview-ID levert ook na een retry of herstart dezelfde snapshot op; een nieuw ophaalmoment levert een nieuwe snapshot op, geen tweede identiteit.
- `GET /api/bol/products/{ean}/snapshots` haalt maximaal 50 snapshots op, nieuwste meetmoment eerst, zonder bol-aanroep of credentials. Ook beschikbaar zonder eerst een live preview op te halen.

Niet-opgeslagen previews leven maximaal 15 minuten in een begrensde procescache van 256 items. Herstart, capaciteitsuitzetting of verlopen preview geeft HTTP 410: opnieuw ophalen. Deze lokale versie vereist één backendproces; meerdere workers vereisen een gedeelde previewcache. Een willekeurige previewreferentie is geen OAuth-token, maar geeft in deze lokale app wel toegang tot de bijbehorende opslagactie. De backend heeft nog geen gebruikersauthenticatie: alleen lokaal gebruiken. CORS staat GET/POST en Content-Type toe voor de bestaande localhost-origins.

`complete` betekent dat catalogus en ratings succesvol verwerkt zijn, niet dat ieder optioneel veld aanwezig is. `partial` betekent dat ratings ontbreken; dit wordt zichtbaar opgeslagen met een veilige melding en adapterfoutcode (geen ruwe upstream-response of gegarandeerde upstream-HTTP-code). Een mislukte catalogusaanvraag levert geen opslagbare preview op. Er is nog geen persistente auditlog van volledig mislukte aanvragen.

## Interface en versheid

Na een geslaagde preview verschijnt de expliciete opslagknop. Ook gedeeltelijke previews kunnen worden opgeslagen. De gebruiker kan opgeslagen metingen voor de ingevoerde EAN bekijken zonder nieuwe bol-aanvraag. De interface toont bron, meetmoment, opslagtijd, ouderdom bij weergave en volledigheid. Er is geen universele versheidsdrempel of automatische verversing. Het previewmeetmoment is het voltooiingsmoment van de opeenvolgende catalogus/ratings-aanvragen; dit is geen door bol verstrekte wijzigingsdatum.

## Verificatie

Volledige backend- en frontendtests plus production build. Tests gebruiken nepcredentials en tijdelijke SQLite-databases. Regressiedekking omvat CSV-duplicates, behoud van prijzen/scores, atomair opslaan, gelijktijdige retries, migratieherhaling, verlopen previews, herkomst, gedeeltelijke metingen, inputvervalsing en veilige foutmeldingen. Voor deze uitbreiding is geen live bol-aanvraag nodig.
