# Sprint 4.1 — Financial Engine v2

## Scope en architectuur

Deze versie levert uitsluitend een afzonderlijke financiële berekening. V1-scores, verdicts, ProductDNA, CSV-contracten, opgeslagen productvelden en het dashboard blijven intact. Geen nieuwe Opportunity-, Demand-, Competition- of Risk-logica. Geen databasewijziging, automatische opslag, live bol-aanvraag of dependency-update.

`app/analysis/financial_v2.py` bevat gevalideerde inputmodellen, prijsselectie en een zuivere rekenfunctie `calculate_financial(inputs, as_of=..., market_payload=..., snapshot_id=...)`. De functie heeft geen I/O, klokafhankelijkheid of mutaties. De aanroeper levert het rekentijdstip aan. `app/api/financial.py` is de afzonderlijke read-only adapter: deze leest zo nodig een bestaande marktsnapshot via een SQLite-verbinding in `mode=ro` en geeft het resultaat terug. Registratie van deze router is de enige wijziging aan bestaande productiecode.

Outputversies: `financial_engine_version=2.0.0-financial.1`, `input_schema_version=1`, `policy_version=financial-nl-new-1`. Dit is geen vervanging van de bestaande Decision Engine. Alle bedragen en percentages worden met Decimal-precisie 40 berekend, zonder tussenafronding, en als decimale strings met vier decimalen teruggegeven (ROUND_HALF_UP). De UI kan later afzonderlijk op centen formatteren.

## Inputmodel en economische betekenis

Alle financiële velden zijn optioneel/null; onbekende bedragen worden nooit stilzwijgend nul. Elke aangeleverde inputgroep vereist provenance. Een waarde nul blijft een expliciete waarde. Geen defaults uit legacy `products`: daar is onder meer de btw-basis niet vastgesteld.

`FinancialInputs`:

| Veld | Model/betekenis |
|---|---|
| `currency` | Alleen EUR |
| `scenario_mode` | `conservative` (standaard) of expliciet `manual` |
| `planned_sale_price` | `amount`, `vat_basis` inclusive/exclusive, provenance |
| `sales_vat_rate` | `value` in procentpunten, provenance |
| `landed_purchase_cost` | CostInput: volledige inkoop inclusief relevante inboundkosten/douane |
| `fulfilment_cost` | CostInput: som van uitgaande fulfilment, verzending en verpakking; geen automatische toeslagen |
| `advertising_cost` | CostInput: advertentiekosten per eenheid |
| `returns_loss_reserve` | CostInput: verwachte retour-/verlieskosten per eenheid |
| `other_allocated_cost` | CostInput: overige daadwerkelijk opgenomen kosten per eenheid |
| `commission` | Vast deel, percentage, btw-behandeling variabel deel en tariefgeldigheid |

`CostInput` bevat `amount`, `vat_basis`, `vat_rate_percent`, `input_vat_recoverable` en `provenance`. Btw-basis:

- `inclusive`: bedrag inclusief kosten-btw; bij aftrekbaarheid delen door `1+t/100`, anders hele bedrag als kosten.
- `exclusive`: bedrag exclusief kosten-btw; bij aftrekbaarheid ongewijzigd, anders vermenigvuldigen met `1+t/100`.
- `effective`: gebruiker levert al de economische kosten inclusief alle niet-aftrekbare belasting. Extra btw-rate/aftrekbaarheidsvelden zijn dan ongeldig, om dubbele aanpassing te voorkomen.

Voor inclusive/exclusive zijn tarief en aftrekbaarheid expliciet nodig. Een ontbrekende btw-declaratie wordt niet als aftrekbaarheid geïnterpreteerd. Een btw-tarief van 0 is toegestaan en verschilt van null. Specifieke regelingen zoals marge-btw worden niet automatisch berekend; er is geen automatische bepaling van belastingplicht of toepassing van een standaard 21%.

`CommissionInput` bevat `fixed_fee` (CostInput), `variable_rate_percent`, `variable_fee_vat_basis`, `variable_fee_vat_rate_percent`, `variable_fee_input_vat_recoverable` en provenance. Het variabele bedrag wordt steeds berekend over de scenarioverkoopprijs inclusief omzet-btw. De genoemde btw-velden bepalen de economische kosten van dat commissiedeel; niet de grondslag voor het percentage.

Tariefgeldigheid moet expliciet vaststaan: `flat_tariff_confirmed=true`, of een inclusief prijsinterval `valid_from_gross_price`–`valid_to_gross_price`. Een opgegeven interval heeft voorrang en begrenst het tarief ook als flat is aangevinkt. Buiten dat interval blijft commissie onbekend. Zo wordt een eventuele prijsspecifieke korting niet ongecontroleerd naar de stresstest doorgetrokken. Geen automatische commissie-API of tariefstaffels in deze sprint.

Validatie: verkoopprijs strikt positief; kosten niet-negatief; bedragen maximaal EUR 1 miljard per input; maximaal vier decimalen; tarieven 0–100 procentpunten; geen booleans als bedragen, NaN of oneindigheid. Ongeldige/tegenstrijdige btw-bases, onlogische commissie-intervallen, extra velden, ontbrekende provenance, tijdstippen zonder tijdzone en toekomstige brondata worden afgewezen. Ontbrekende gegevens zijn daarentegen een geldige onvolledige aanvraag, geen economische nul.

## Formules

Na omzetting van de geplande prijs naar inclusief btw en normalisatie van alle kosten:

```text
P = gekozen scenarioverkoopprijs inclusief omzet-btw
v = sales_vat_rate / 100
K = economische landed purchase cost
F, A, T, O = economische fulfilment-, advertentie-, retour-/verlies- en overige kosten
B(P) = economisch vast commissiedeel + economisch variabel deel bij P

Omzet exclusief btw = P / (1 + v)
Bijdrage per stuk = P / (1 + v) - K - F - A - T - O - B(P)
Contributiemarge (%) = 100 × bijdrage / omzet exclusief btw
Voorraad-ROI (%) = 100 × bijdrage / K
```

Bij K=0 blijft bijdrage berekenbaar, maar ROI=null met `roi_reason=zero_landed_purchase_cost`. Bij K onbekend is ook bijdrage onbekend. Negatieve bijdrage/marge/ROI blijven negatief; er zijn geen scorecaps of koopadviezen. Outputlabel is altijd **Bijdrage per stuk na opgenomen kosten**, niet nettowinst. Er wordt niets verondersteld over niet-opgenomen overhead of ondernemingsbelasting.

Stresstest:

```text
P_stress = 0,90 × P
F_stress, A_stress, T_stress, O_stress = 1,10 × oorspronkelijke economische kosten
K blijft gelijk
Commissie wordt opnieuw berekend bij P_stress, inclusief controle van tariefgeldigheid
Vast commissiedeel blijft gelijk indien dat tarief voor de stressprijs geldig is
```

## Conservatieve prijsselectie

Een complete, volledig gepagineerde NL/NEW-marktsnapshot in EUR/v10 is bruikbaar tot en met 24 uur na meten. Toekomstige, oudere, onvolledige, corrupte of lege metingen leveren geen geschikte prijs. Individuele aanbiedingen moeten geldige positieve prijzen, unieke offer-ID's, expliciete beste-markering en de juiste land/conditie hebben. De opgeslagen afgeleide minimumprijs wordt niet blind vertrouwd: de selectie wordt opnieuw uit de officiële offers berekend.

1. Kies de laagste prijs onder bol-beste aanbiedingen.
2. Als er geen beste aanbieding is: de laagste geldige aanbieding.
3. Kies het minimum van die referentie en de handmatige geplande prijs, beide inclusief btw.

Zonder handmatige prijs ontstaat geen basisprijs. Zonder bruikbare marktprijs blijft het conservatieve basisscenario onbekend; het resultaat bevat daarnaast het afzonderlijke handmatige scenario. Alleen met `scenario_mode=manual` wordt dat handmatige scenario expliciet als basis geselecteerd. `sale_price` in ProductRadar wordt nooit aangepast.

De output geeft `selected_from`, `reason`, de oorspronkelijke geplande brutoprijs, referentieprijs, offer-ID, meetmoment, snapshot-ID en herkomst terug. Dit prijsbeleid is een rekenaanname, geen voorspelling van verkoopbaarheid of koopblokkans. Kostenprovenance blijft zichtbaar; deze financiële fundering berekent nog geen confidence/kwaliteitsscore of leeftijdskorting voor kosten.

## API en output

`POST /api/financial/v2/calculate` met JSON:

```json
{
  "ean": "4006381333931",
  "market_snapshot_id": null,
  "inputs": {
    "scenario_mode": "conservative",
    "planned_sale_price": {
      "amount": "24.20",
      "vat_basis": "inclusive",
      "provenance": {
        "kind": "manual_or_imported",
        "source": "Voorbeeld van een geplande verkoopprijs",
        "recorded_at": "2026-01-01T00:00:00Z"
      }
    }
  }
}
```

Dit minimale voorbeeld is bewust onvolledig: ontbrekende kosten en btw blijven null. Voor een volledige berekening moeten alle kostenposten en commissiecomponenten expliciet zijn ingevuld, eventueel met nul als die kosten werkelijk niet van toepassing zijn.

Zonder `market_snapshot_id` leest de API de nieuwste opgeslagen marktmeting voor de EAN. Een nieuwere gedeeltelijke meting wordt niet stilzwijgend vervangen door een oudere complete. Met een expliciet ID moet ook de EAN overeenkomen. Een ontbrekend specifiek ID geeft 404, ongeldige invoer 422, een databaseleesfout een veilige 503. Onbekende inputs of een ontbrekende automatische marktmeting geven 200 met onvolledige resultaten. De route haalt niets live op en schrijft niets, ondanks de POST-vorm voor het rekenverzoek.

Antwoord: `{ean, v2_financial}`. `v2_financial` bevat:

- versie/policy/as_of/currency en de originele expliciete inputs;
- `price_selection` met reden en herkomst;
- `manual`, `base`, `stress`, elk met status, prijs, omzet exclusief btw, omzet-btw, genormaliseerde kosten, vaste/variabele/totale commissie, bijdrage, contributiemarge, voorraad-ROI en ontbrekende inputcodes;
- `calculation_provenance`, afhankelijkheden, stressaannames en afrondingsbeleid.

Provenance bevat `kind` (`official_measured`, `manual_or_imported`, `derived`, `estimated`), `source`, `recorded_at` en optioneel `snapshot_id`. Bij samengestelde kostendeclaraties geldt de provenance voor bedrag én btw-declaratie. Invoerherkomst is uitdrukkelijk **caller_declared**; de API verifieert geen facturen of leveranciersclaims. Alleen marktdata wordt door de server uit bestaande snapshots geladen. Afgeleide prijskeuze en berekeningen bevatten afhankelijkheden naar hun inputs. Geen automatisch opgeslagen analyses in Sprint 4.1.

## Verificatie

Het ontwerpvoorbeeld gebruikt P=24,20, btw=21%, K=7, F=3, retourreserve=1, advertentie/overige kosten=0, vaste commissie=0,58 en variabele commissie=10% (effectieve kosten, vlak tarief bevestigd): omzet exclusief btw=20; commissie=3; bijdrage=6; marge=30%; ROI=85,7143%. Stress: commissie=2,758; bijdrage=3,842. Alle tarieven/bedragen zijn fictieve testinputs.

Tests dekken verlies, nul versus ontbrekende inkoop, ontbrekende kosten, btw-bases en aftrekbaarheid, nul-btw, commissiecomponenten en prijsintervallen, conservatieve prijsselectie, ongeschikte snapshots, strikte validatie, provenance, zuiverheid en ongewijzigde database/v1-output via de API. De bestaande v1-sample plus alle vijf seedproducten zijn vóór wijzigingen vastgelegd als volledige golden outputs. Vergelijking omvat alle scores, geldbedragen, verdicts, redenen en ProductDNA — niet alleen ranges. Alle bestaande regressietests blijven behouden.
