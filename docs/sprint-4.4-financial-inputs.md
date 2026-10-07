# Sprint 4.4 — Financial Inputs & Provenance

Branch: `feature/financial-inputs-v2`, vanaf main `113fc5d51682bc5a4877a0434f5a1fda74e214e5`.

## Architectuur en database

Financiële v2-invoer staat los van `products`. Eén JSON-profiel bevat `schema_version: "1"`, de ongewijzigde `FinancialInputs`, een optionele kostenuitsplitsing en referenties. De engine rekent uitsluitend met expliciet bevestigde landed- en logistieke totalen. Inkoop/inbound en verzending/verpakking/handling zijn uitsplitsingen, geen extra aftrekposten. Zijn onderdelen en een totaal ingevuld, dan moeten alle onderdelen economisch bepaalbaar zijn, inclusief expliciete nullen waar van toepassing, en moet hun som overeenkomen met het totaal (tolerantie €0,0001). Onbekende onderdelen worden niet aangevuld. Zonder bevestigd totaal kan de API wel een afgeleid totaal voorstellen, maar dat voorstel wordt nooit automatisch financiële invoer.

Additieve tabel `financial_input_versions`: id, product_id (foreign key), version, schema_version, saved_at (UTC), profile_hash, payload en preview_id. Unieke sleutels op (product_id, version) en (product_id, preview_id). Iedere wijziging voegt een nieuwe volledige versie toe; oude versies blijven ongewijzigd beschikbaar. Er worden geen bestaande productvelden, analyses of snapshots bijgewerkt.

Opslaan gebruikt één SQLite `BEGIN IMMEDIATE`-transactie, een optimistische expected_version en een door de server afgegeven previewreceipt die bij product, versie en profielhash hoort. Een herhaald identiek verzoek met dezelfde receipt retourneert de bestaande versie. Een achterhaalde versie of gewijzigde preview geeft 409; een verlopen/ongeldige receipt 410. De receipt verloopt na 15 minuten, is proceslokaal en heeft een begrensde cache. Na een backendherstart moet een nog niet opgeslagen preview opnieuw worden berekend. Opslagfouten rollen de gehele transactie terug.

De herhaalbare migratie draait bij normale backendstartup, binnen de bestaande migratietransactie, of bij de eerste expliciete opslag. Deze sprint heeft de echte gebruikersdatabase niet gemigreerd of geschreven. Migratie/atomiciteit zijn op tijdelijke databases getest. Zonder nieuwe tabel blijven read-only endpoints en vergelijking werken.

## Provenance en validatie

Elke financiële inputgroep en ieder uitsplitsingsonderdeel heeft `kind`, `source` en een tijdzonebewuste `recorded_at`. Mogelijke kinds: `manual_or_imported`, `official_measured`, `derived`, `estimated`. Een kostengroep omvat bedrag en de bijbehorende btw-behandeling; gebruik een bronbeschrijving die beide onderbouwt. Verkoop-btw, geplande prijs, vast commissiedeel en variabel commissiedeel hebben afzonderlijke provenance. Optionele import-, snapshot- en toekomstige regelreferenties staan per inputpad in `references`.

Officiële financiële metingen kunnen momenteel uitsluitend een exact verifieerbare relevante bruto bol-aanbiedingsprijs zijn, met overeenkomend product, snapshot, meetmoment en bedrag. Er is nog geen vertrouwde btw-/commissieregelprovider: zulke invoer wordt niet als officieel geaccepteerd. Een ingevulde rule_reference activeert geen automatische regel. Er wordt niets geraden uit het legacy commissiepercentage.

Ontbrekend blijft null, expliciete nul blijft nul. Decimalstrings voorkomen frontendprecisieverlies. De bestaande Financial v2-validatie blijft leidend voor bedragen, precisie, btw-percentages en economisch zinvolle combinaties. Daarnaast zijn toekomstige invoerdatums, onbekende referentiepaden, conflicterende snapshotreferenties en inconsistentie tussen kostentotalen en uitsplitsing verboden. Foutmeldingen tonen geen interne transportdetails of credentials.

## UI-flow

Op productdetail blijft de bestaande v1-calculator intact. Een afzonderlijke financiële editor wordt expliciet geladen en groepeert Inkoop, Belasting, Verkoop, bol-kosten, Logistiek en Overige kosten. Per waarde zijn bedrag/basis, eventuele btw/aftrekbaarheid en herkomst/bron/datum bewerkbaar. Geen btw, commissie of invoerdatum wordt vooraf verzonnen.

Legacy verkoopprijs, inkoopprijs en verzending zijn herkenbare voorstellen. Overnemen vult alleen het bedrag in; basis, bron en datum moeten expliciet worden opgegeven. De serverpreview toont conservatieve prijs met selectiereden en bron/meetmoment, omzet exclusief btw, bijdrage per stuk, contributiemarge, voorraad-ROI en stressprijs/-bijdrage. Bijdrage wordt niet als nettowinst aangeduid. Afgeleide totaalvoorstellen blijven `derived` en vereisen opnieuw bron/datum, preview en bevestiging. Een gewijzigd onderdeel mag een bevestigd totaal niet stilzwijgend vervangen.

Pas na preview en een afzonderlijk bevestigingsvak kan worden opgeslagen. Wijzigingen maken de preview ongeldig; dubbelklikken veroorzaakt geen dubbele aanvraag. Netwerkfouten en versieconflicten geven een herstelbare melding. Versiehistorie is zichtbaar; volledige historische profielen zijn read-only via de versie-API opvraagbaar. Na opslaan kan de bestaande v1/v2-vergelijking opnieuw expliciet worden geladen.

## API en berekeningen

- GET `/api/products/{id}/financial-inputs?version=…`: saved-profiel, versiehistorie, onbevestigde legacyvoorstellen en default_engine v1.
- POST `/api/products/{id}/financial-inputs/preview`: profile + expected_version; retourneert receipt, profielhash, Financial v2-resultaat en afgeleide voorstellen; schrijft niets.
- POST `/api/products/{id}/financial-inputs`: exact previewprofiel + expected_version + preview_id + confirmed true; voegt één versie toe.
- GET `/api/products/{id}/financial-v2?version=…`: berekening met laatste of gekozen financiële versie en huidige opgeslagen marktdata.
- GET `/api/products/{id}/decision-v2?version=…`: ongewijzigde scoring-engine met opgeslagen profiel en bol-bewijs.
- Bestaande comparison/evaluation leest dezelfde laatste versie. Outputs vermelden financial_input_version en financial_profile_id. Een historische profielversie kan met huidige bewijsdata worden doorgerekend; dit wordt niet voorgesteld als een historische analyse op het oorspronkelijke tijdstip. Bewaar voor volledige historische analysereconstructie ook het engine-resultaat, as_of en de betrokken snapshot-ID's.

Alle GET/preview-responses zijn no-store. De bestaande expliciete Financial/Decision v2-API's blijven behouden. Engineversies, formules, scoregewichten en verdictbeleid veranderen niet. Basisprijs = laagste van geplande bruto prijs en geschikte officiële bol-prijs, alleen bij volledige NL/NEW/EUR v10-marktdata van maximaal 24 uur oud. Oudere marktdata levert geen actuele definitieve Opportunity Score op. Stress verlaagt prijs met 10%, verhoogt de door Financial v2 toepasselijk geachte operationele kosten met 10% en herberekent commissie; landed inkoop en vaste commissie worden volgens het bestaande contract niet verhoogd.

## Validatie

- Volledige backend-suite: **301 geslaagd** (279 bestaande + 22 nieuwe). Bestaande v1-, Financial v2-, scoring-, CSV-, bol- en snapshotregressies blijven slagen.
- Volledige frontend-suite: **63 geslaagd** (50 bestaande + 13 nieuwe).
- Next.js 15.5.26 production build: geslaagd, inclusief typecontrole en pagina-generatie.
- `git diff --check` en aanvullende whitespacecontrole van nieuwe bestanden: geslaagd. Secretscontrole van 82 bronbestanden, werk-/staged diffs en lokale logs: 0 bevindingen; backend/.env blijft genegeerd. Geen .env, database of tijdelijk bestand in de 13 wijzigingen.
- Nieuw: versiehistorie, nul/ontbrekend, provenance/referenties, economische validatie, toekomstdata, previewbinding, idempotentie, gelijktijdige versies, SQLite rollback, herhaalbare migratie, kostenuitsplitsing zonder dubbele aftrek, geverifieerde officiële prijs, echte v2-score met complete fixture-inputs, stale marktdata, expliciete UI-bevestiging, late productresponses en dubbele acties.
- Financiële fixture: bijdrage €6,0000; stressbijdrage €3,8420. Opgeslagen complete invoer met recente fixturemarkt geeft een echte v2-score; een vier dagen oude meting blijft score null.
- Read-only API-smoke op alle acht echte producten: GET inputs, Financial v2, Decision v2 en vergelijking geslaagd; databasehash vóór/na identiek. Geen echte invoer opgeslagen en geen live bol-aanvragen.
- Bestaande FastAPI startup- en react-test-renderer-deprecationmeldingen blijven; geen nieuwe testfouten. Geen dependencywijzigingen.

## Acht bestaande producten — alleen inventarisatie

Alle acht hebben nog geen bevestigd financieel v2-profiel en geen opgeslagen relevante marktmeting. Hun actuele definitieve v2-score blijft daarom null. Voor elk ontbreekt dezelfde financiële bevestiging: geplande verkoopprijs met btw-basis, verkoop-btw, landed inkoop inclusief inbound en belasting/aftrekbaarheid, volledige logistiek inclusief verpakking/handling, vaste én variabele commissie inclusief btw en tariefgeldigheid voor basis/stress, advertenties, retour-/verliesreserve en overige kosten, plus provenance/bron/datums. Een werkelijk niet van toepassing zijnde kostenpost kan de gebruiker expliciet als nul bevestigen; onbekend wordt niet nul.

| ID | Product | Aanvullende marktvoorwaarde |
| --- | --- | --- |
| 1 | WD-40 Smart Straw 400 ml | EAN ontbreekt; identiteit en actuele volledige marktmeting nodig |
| 2 | Werkhandschoenen nitril 12 paar | EAN ontbreekt; identiteit en actuele volledige marktmeting nodig |
| 3 | EHBO-kit DIN 13164 | EAN ontbreekt; identiteit en actuele volledige marktmeting nodig |
| 4 | Ventieldoppenset aluminium 4-delig | EAN ontbreekt; identiteit en actuele volledige marktmeting nodig |
| 5 | Automattenset universeel 4-delig | EAN ontbreekt; identiteit en actuele volledige marktmeting nodig |
| 6 | Telefoonhouder auto | EAN aanwezig; identiteit en actuele volledige marktmeting nodig |
| 7 | Microvezeldoeken 10-pack | EAN aanwezig; identiteit en actuele volledige marktmeting nodig |
| 8 | Bandenspanningsmeter digitaal | EAN aanwezig; identiteit en actuele volledige marktmeting nodig |

De bestaande inkoop-, verkoop- en verzendbedragen zijn beschikbaar als voorstellen, maar onderbouwen nog geen v2-kostencontract. Bestaande geschatte verkoopranges worden niet automatisch vraagbewijs. Betrouwbaar vraag-/risicobewijs blijft relevant voor score-uitleg en een kansrijk verdict; deze sprint voegt geen nieuwe score-invoer of beleid toe.

## Gewijzigde bestanden

Nieuw: `backend/app/api/financial_inputs.py`, `backend/app/services/financial_profiles.py`, `backend/tests/test_financial_profiles.py`, `frontend/components/FinancialEditor.tsx`, `frontend/lib/financial-form.ts`, `frontend/tests/financial-inputs.test.cjs`, dit rapport.

Bestaand aangepast: `backend/app/core/database.py`, `backend/app/main.py`, `backend/app/services/comparison.py`, `frontend/app/globals.css`, `frontend/components/ProductDetail.tsx`, `frontend/tests/product-page.test.cjs` (TypeScript-loader voor de nieuwe editorimport).

Geen commit, push of merge. Geen v1/v2-formule-, dependency-, CSV-, credential-, snapshot- of gebruikersdatawijzigingen.
