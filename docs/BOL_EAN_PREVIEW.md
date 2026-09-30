# Sprint 3.1 — alleen-lezen bol EAN-preview

De preview haalt cataloguscontent en de sterrenverdeling op via de bol Retailer API v10. Er worden geen ProductRadar-producten aangemaakt of gewijzigd. CSV-import en Decision Engine blijven onafhankelijk. Het aantal beoordelingen en het gemiddelde zijn afgeleid van de bol-sterrenverdeling, geen verkoopvolumes. Een catalogusclassificatie is geen webshopcategorieboom.

## Lokaal instellen

Stel uitsluitend in het proces van de **backend** deze environment variables in:

- `BOL_CLIENT_ID`: client-ID uit de API-instellingen van je bol-verkoopaccount.
- `BOL_CLIENT_SECRET`: bijbehorend client-secret.

Beide zijn optioneel zolang je de bol-preview niet gebruikt. Zonder configuratie blijft ProductRadar werken en geeft alleen de preview een duidelijke melding. Herstart de backend na het wijzigen van configuratie.

Je kunt ook zelf `backend/.env.example` kopiëren naar `backend/.env`, de twee waarden lokaal invullen en vanuit `backend` starten met:

```text
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file .env
```

Een `.env` wordt alleen geladen wanneer je expliciet `--env-file .env` gebruikt. `.env` en `.env.*` zijn genegeerd door Git; alleen `.env.example` mag worden bijgehouden. Zet geen credentials in de frontend, `NEXT_PUBLIC_*`, Git, screenshots of chat. Voor lokaal gebruik luistert bovenstaande opdracht alleen op localhost. De app heeft nog geen gebruikersauthenticatie; publiceer deze backend niet als openbare gedeelde API.

## Gedrag en grenzen

- `GET /api/bol/ean-preview/{ean}`: valideert 13 ASCII-cijfers en het EAN-controlecijfer.
- Upstream uitsluitend tokenaanvraag en twee GET-aanvragen naar vaste bol-hosts. Geen aangeboden URL's, redirects of bol-schrijfendpoints.
- Catalogus: `GET /retailer/content/catalog-products/{ean}`, taal `nl`.
- Ratings: `GET /retailer/products/{ean}/ratings`.
- OAuth2 Client Credentials; token in procesgeheugen met vervalmarge, hergebruik en lock tegen gelijktijdige tokenaanvragen.
- Bij 401 één tokenvernieuwing en één herhaling. Bij 429 cooldown; geen automatische retrylus. Timeouts zijn begrensd.
- Foutteksten zijn lokaal gedefinieerd; upstream bodies, exceptions en tokens worden niet gelogd of teruggestuurd. Alleen geselecteerde catalogusvelden en gecontroleerde ratings verlaten de adapter.
- Ontbrekende ratings geven een gedeeltelijke preview met waarschuwing. Nul beoordelingen geeft geen gemiddelde van nul sterren.
- Configuratie/token zijn niet persistent. De preview schrijft niet naar SQLite en heeft geen importknop.

De tests gebruiken uitsluitend nepcredentials en `httpx.MockTransport`; er is geen live bol-call nodig. Testaccounttoegang en echte responses pas nadat de eigenaar credentials lokaal heeft ingesteld. De eerste versie doet geen bulkimport, historische opslag, White Spots, ranglijsten of verkoopvolumeschattingen.

## Controles

Vanuit `backend`: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`

Vanuit `frontend`: `npm test` en `npm run build`

Officiële contracten: https://api.bol.com/retailer/public/Retailer-API/authentication.html en https://api.bol.com/retailer/public/redoc/v10/retailer.html
