# Sprint 4.5 — Market Refresh & Freshness

Branch `feature/market-refresh-freshness` vanaf main `b6fdf89405010fb38e03008401bc3cc076821d4e`. Geen commit, push of merge.

## Centrale selectie en freshness

`services/freshness.py` is de centrale opgeslagen-marktreader en classificatie. De databasekolommen selecteren NL/NEW, daarna wordt de nieuwste relevante rij gekozen, inclusief incomplete/foutieve rijen. Ongeldige tijden blokkeren een fallback. Oudere schema's zonder segmentkolommen worden read-only ondersteund; ongeldige payloads worden niet stilzwijgend verwijderd.

| Status | Regel |
| --- | --- |
| current | Volledig gevalideerde bruikbare aanbiedingen, leeftijd ≤24 uur |
| stale | Zelfde volledigheid, leeftijd >24 en ≤72 uur |
| historical | Zelfde volledigheid, leeftijd >72 uur |
| missing | Geen meting of complete meting zonder bruikbare aanbiedingsprijs |
| incomplete | Nieuwste relevante meting is gedeeltelijk |
| error | Nieuwste poging mislukt, onderbroken, nog bezig of payload/tijd ongeldig |

De gecombineerde gebruikerscategorie incomplete/error is in de API uitgesplitst voor een gerichte verklaring. Leeftijd gebruikt tijdzonebewuste UTC-tijden en exacte duur; er wordt vóór classificatie niet afgerond. Outputs bevatten status, reason, age_hours, meet-/pogingmoment, snapshot-ID, bron/versie, as_of, usable_for_current_analysis en freshness_version `market-freshness/1.0`.

Validatie van aanbodvelden en financiële prijsbruikbaarheid hergebruikt de bestaande pure engines. De Financial v2-harde grens en de bestaande scoring-gewichten voor dataversheid blijven exact intact. De nieuwe classifier voegt geen scoreformules toe: readers, vergelijking en Decision-API adapters delen de classificatie. Officiële aanbodvelden zijn official_measured; tellingen, prijsselectie, leeftijd en freshness zijn derived. Een poging zonder ontvangen aanbiedingen claimt geen officiële aanboddata. Verkoopschattingen blijven estimated en worden niet automatisch gebruikt als vraagbewijs.

Een nieuwere incomplete/mislukte poging vervangt niet de oudere rij, maar blokkeert het gebruik ervan als huidige prijs. Oudere metingen blijven zichtbaar als historische context. Een lopende/onderbroken poging zonder opgeslagen snapshot wordt door de reader als onbeschikbare marker (id 0, geen echte snapshot-ID) aangeboden aan de ongewijzigde engines; dat is geen gefabriceerde bol-prijs. Zo blijft ook een opslagfout of processcrash fail-closed. De expliciete Financial v2-API voor een door de caller gekozen snapshot-ID blijft behouden; dit is geen automatische fallback en de bestaande 24-uursprijsgrens blijft gelden.

## Refreshservice en additieve opslag

De refreshservice hergebruikt `get_bol_client`, `BolClient.preview` en `save_snapshot`: bestaande OAuth/tokenhergebruik, veilige normalisatie, catalogus, ratings, NL/NEW offers, paginering, identiteit en snapshots. Er is geen tweede bol-client. Een refresh kan daardoor ook catalogus-/ratingdata vastleggen; de oude snapshots worden niet gewijzigd.

Nieuwe tabel `bol_market_refresh_requests`: request_id (UUID, primary key), EAN, started_at, lease_until, state running/done, snapshot_id (foreign key), error_code; index op EAN/tijd. Migratie is additief en transactioneel bij normale backendstartup, of bij de eerste expliciete refresh. Na ontwikkeling is de echte migratie gecontroleerd via normale backendstartup toegepast, voorafgegaan door een nieuwe consistente databasebackup (Sprint 4.5). Alleen deze tabel/index zijn toegevoegd; oorspronkelijke inhoud is behouden. Zie de pre-commit praktijktest hieronder.

Een `BEGIN IMMEDIATE`-transactie reserveert de aanvraag per EAN. Gelijktijdige actieve refresh geeft 409, ook met andere request-ID of vanuit een tweede worker. De lease bedraagt 4500 seconden (75 minuten) voor begrensde recovery bij processuitval. Een verlopen aanvraag blijft op reads onbeschikbaar totdat een expliciete nieuwe refresh bewijs opslaat; de lease maakt oude prijzen nooit opnieuw actueel. Een nog werkelijk lopende worker mag niet langer dan de lease duren; die limiet is een bekende operationele randvoorwaarde. Geen automatische scheduler, lease-ververser of achtergrondmonitor.

Een herhaald voltooid request-ID retourneert hetzelfde snapshotresultaat zonder bol-calls. Zelfde ID met andere EAN wordt geweigerd. De frontend hergebruikt bij een onzekere netwerkuitkomst de aanvraag-ID. Snapshotopslag en het afronden van de refreshregistratie gebeuren in één transactie via een optionele interne on_saved-callback op de bestaande snapshotwriter. Het bestaande save_snapshot-contract zonder callback blijft gelijk.

Catalogus/auth/netwerkfalen vóór offers worden als minimale failed-preview met unavailable marktdata opgeslagen. Er wordt geen catalogus, rating of prijs verzonnen. Partial offers worden met de bestaande snapshotstructuur bewaard. Oude historie blijft behouden. Alleen bekende veilige foutcodes/meldingen worden teruggegeven; raw exceptions/upstream bodies/credentials komen niet in responses of opslag.

## API/UI

- GET `/api/products/{id}/market-status`: centrale freshness, can_refresh, identiteitsmelding en maximaal 50 historische contextmetingen. Leest alleen opgeslagen data; no-store.
- POST `/api/products/{id}/market-refresh`, body `{request_id: UUID}`: expliciete refresh plus opslag; retourneert opgeslagen status en refresh outcome saved/failed, snapshot-ID, duplicate, error_code en begrijpelijke message. Een opgeslagen failed/partial poging gebruikt HTTP 200 met expliciet outcome failed, geen verborgen succes. Input/conflict/opslagfouten gebruiken onder meer 400/409/503. Niet bestaand product 404; ongeldige body 422.
- Decision v2 analyze en opgeslagen productanalyse voegen market_freshness toe. De vergelijking gebruikt hetzelfde centrale market-object. Financial v2's automatische marktselectie gebruikt dezelfde opgeslagen-marktreader. Pure reken- en scoremodules blijven ongewijzigd.

Productdetail toont centrale status, ouderdom, bron, officiële prijzen en afgeleide tellingen, relevante aanbieding en beschikbare fulfilment/leverdata. Zonder geldige EAN ontbreekt de refreshknop. Expliciete refresh toont loading, blokkeert dubbele klikken en verbergt de vorige v2-beoordeling tijdens ophalen. Na bevestigde refresh wordt status opnieuw met GET geladen en de vergelijking uit opgeslagen data opnieuw berekend. Bij onbekende netwerkuitkomst wordt oude data niet opnieuw actueel getoond; gebruiker kan de status opnieuw laden of met dezelfde request-ID herhalen. Historie is expliciet context, ook wanneer een oude contextmeting qua leeftijd nog binnen 24 uur valt.

De UI classificeert geen tijd zelf: zij formatteert alleen backendstatus en leeftijd, met het backend-analysemoment zichtbaar. Er is geen timer/scheduler die nieuwe bol-data ophaalt. Een lang openstaande pagina toont de status van het laatste uitleesmoment; opnieuw laden vraagt een nieuwe classificatie op.

## Tests en verificatie

- Backend: **324 geslaagd** (301 bestaande + 23 nieuwe). Exact 24 uur, 24 uur +1 seconde, exact 72 uur, 72 uur +1 seconde, missing, corrupt/future, partial/error, recente complete + nieuwere failed, volledige refresh, paginering/429, auth/404/5xx, duplicate/concurrent, interrupted lease, opslagrollback, verkeerde/ontbrekende EAN en historische inhoud.
- Frontend: **79 geslaagd** (63 bestaande + 16 nieuwe). Alle buckets, expliciete actie/no-EAN, loading, dubbele klikken, herladen uit opslag, contextlabels, fout/conflict, onzekere netwerkretry met dezelfde ID, productwissel en verbergen/herladen van v2.
- Next.js 15.5.26 production build, types en pagina-generatie geslaagd.
- `git diff --check` en whitespacecontrole van nieuwe bestanden geslaagd. Secretscontrole: 90 bronbestanden, werk-/staged diffs, 0 lokale logs, 0 bevindingen; .env blijft genegeerd. Scopecontrole: uitsluitend de 21 bedoelde bestanden, niets staged; geen databases/backups of tijdelijke ontwikkelbestanden in de wijzigingen.
- De gedeelde presentatiefixtures zijn vernieuwd voor current/historical en centrale metadata; alle oorspronkelijke v1- én v2-analyseresultaten zijn daarbij exact gelijk gebleven.
- Financial v2, Decision v2, v1, CSV, profielen en bestaande snapshotregressies slagen. Product- en financiële profielrijen blijven bij refresh exact gelijk; oude snapshotpayloads blijven identiek.
- Ontwikkeltests uitsluitend met mocks/fixtures. Vervolgens is op gebruikersverzoek één gecontroleerde live pre-commit refresh uitgevoerd op een tijdelijk product; zie hieronder. Read-only inventarisatie gebruikt een externe-call blokkade en bevestigt identieke databasebytes vóór/na plus integrity_check en foreign_key_check.
- Bestaande FastAPI startup- en react-test-renderer-deprecations blijven. Geen dependencywijzigingen.

## Acht bestaande producten — read-only bevindingen

| ID | Product | EAN / refreshbaarheid |
| --- | --- | --- |
| 1 | WD-40 Smart Straw 400 ml | EAN ontbreekt; niet refreshbaar |
| 2 | Werkhandschoenen nitril 12 paar | EAN ontbreekt; niet refreshbaar |
| 3 | EHBO-kit DIN 13164 | EAN ontbreekt; niet refreshbaar |
| 4 | Ventieldoppenset aluminium 4-delig | EAN ontbreekt; niet refreshbaar |
| 5 | Automattenset universeel 4-delig | EAN ontbreekt; niet refreshbaar |
| 6 | Telefoonhouder auto | EAN ingevuld, controlecijfer ongeldig; niet refreshbaar |
| 7 | Microvezeldoeken 10-pack | EAN ingevuld, controlecijfer ongeldig; niet refreshbaar |
| 8 | Bandenspanningsmeter digitaal | EAN ingevuld, controlecijfer ongeldig; niet refreshbaar |

Geen van de acht is nu direct refreshbaar. Alle acht hebben freshness missing, geen bevestigd financieel profiel en score null. Na het door de gebruiker opgeven/corrigeren van een echte EAN en een eventuele succesvolle refresh ontbreken nog expliciete geplande prijs/btw-basis, verkoop-btw, landed inkoop/inbound, volledige logistiek/verpakking/handling, vaste + variabele commissie met btw/tariefcontext, advertenties, retour-/verliesreserve en overige kosten met bron/datums. Vraag-/risicobewijs is eveneens niet voldoende onderbouwd; bestaande geschatte sales zijn geen officiële bol-verkopen. De exacte na-refresh readiness kan pas met een echte meting worden bepaald. Er zijn geen EAN's, bedragen of andere gegevens ingevuld/gecorrigeerd.

## Gewijzigde bestanden

Nieuw: backend/app/api/market_refresh.py; backend/app/services/freshness.py; backend/app/services/market_refresh.py; backend/tests/test_market_refresh.py; frontend/components/MarketFreshness.tsx; frontend/components/MarketRefresh.tsx; frontend/tests/market-refresh.test.cjs; dit rapport.

Bestaand aangepast: backend/app/api/decision.py; backend/app/api/financial.py; backend/app/api/financial_inputs.py; backend/app/core/database.py; backend/app/main.py; backend/app/services/comparison.py; backend/app/services/snapshots.py; backend/tests/fixtures/comparison_scenarios.json; backend/tests/test_comparison.py; backend/tests/test_snapshots.py; frontend/components/DecisionComparison.tsx; frontend/components/ProductDetail.tsx; frontend/lib/comparison-types.ts.

## Grenzen en vervolgstappen

Geen live toegang voor de acht echte producten geverifieerd. De bestaande accountconfiguratie is wel succesvol getest met het eerder geverifieerde voorbeeld-EAN. Refreshbaarheid betekent alleen een gevalideerde EAN; beschikbaarheid bij bol volgt pas uit een echte aanvraag. De huidige refresh gebruikt de volledige bestaande preview en maakt extra catalogus-/ratingcalls; offers-only optimalisatie is toekomstwerk. Historie en aanvraag-ID's hebben geen automatische retention cleanup. Identiteitsconflicten blijven via de bestaande engine zichtbaar. Freshness maakt op zichzelf geen financieel onvolledig product geschikt voor inkoop en verandert v2 niet in dashboardbeleid.

## Pre-commit praktijktest op de echte lokale database

- Nieuwe SQLite online backup: `productradar-before-sprint45-20261007T091328Z.db`, buiten de repository. Inhoud en integriteit vooraf gecontroleerd; de Sprint 4.4-backup is niet als enige herstelmogelijkheid gebruikt.
- Normale uvicorn/startup op lokale testpoort. Uitsluitend refreshtabel/index toegevoegd; alle bestaande schema's, records en sequences identiek vóór/na migratie.
- Tijdelijk testproduct, EAN `9781538744017` (eerder geverifieerd in Sprint 3.3), met uitsluitend fictieve expliciete financiële testinvoer. Geen van producten 1–8 aangepast.
- Echte React-refreshknop programmatisch tegen de normale backend: missing → één live preview/OAuth/offersketen → snapshot → current. OAuth, catalogus, ratings en offers elk HTTP 200; één offerspagina.
- Live meetmoment `2026-10-07T09:13:33.082736+00:00`, exact ongewijzigd tussen adapter, opgeslagen payload/rij en read-back. NL/NEW v10: één aanbieding, één unieke verkoper, prijsrange/relevante prijs €31,89; bol-beste aanbieding, FBB. Officiële offerdata official_measured; freshness/leeftijd/tellingen derived.
- Financial/Decision v2 gebruikten het opgeslagen snapshot en financieel profiel versie 1. De fictieve testberekening gaf bijdrage €6,0000 en v2-score 59,54; dit zijn geen commerciële conclusies over de acht echte producten. Handmatige testproductvelden, bevestigd profiel en v1-output bleven exact gelijk door refresh.
- Tweede gelijktijdige aanvraag én dezelfde ID terwijl running: 409, geen tweede bol-clientketen. Herhalen na afronding: hetzelfde snapshot, nul extra live calls.
- Daarna alle verdere upstream requests expliciet geblokkeerd. Nieuwere partial en unavailable testmetingen blokkeerden de complete live meting als huidige financiële/v2-basis; de oorspronkelijke live payload bleef byte-for-byte behouden als historie.
- Grenzen getest via de centrale classifier met aangepaste as_of, zonder werkelijk measured_at te herschrijven: exact 24 uur current; +1 seconde stale; exact 72 uur stale; +1 seconde historical.
- Gesimuleerde vastgelopen testlease: vóór verlopen 409; na 4500 seconden refresh_interrupted en nog steeds geen oude huidige prijs; na expliciet verlopen lease een nieuwe aanvraag toegelaten met uitsluitend een fixtureclient. Herstel vereist een nieuwe expliciete refresh, geen automatische fallback.
- Alle tijdelijke producten, financiële versies, identiteit, product-/marktsnapshots en refreshregistraties opgeruimd. Nieuwe tabel/index behouden. Alle oorspronkelijke tabellen/rijen/sequences en v1-resultaten exact gelijk aan de nieuwe backup; acht producten, integrity_check ok, foreign_key_check leeg. Backend beëindigd.
- Geen productiecodefixes nodig. Na de praktijktest backend- en frontendregressies en whitespace/secretscontrole opnieuw uitgevoerd. Geen commit/push/merge; testdrivers, backup en lokale artifacts buiten Git.
