"use client";

type Offer = {
  offerId: string | null; retailerId: string | null; price: number | null; bestOffer: boolean | null;
  fulfilmentMethod: string | null; ultimateOrderTime: string | null;
  minDeliveryDate: string | null; maxDeliveryDate: string | null;
};

export type MarketMeasurement = {
  source: string; api_version: string; country: string; condition: string;
  started_at: string; measured_at: string; status: "complete" | "partial" | "unavailable";
  offers: Offer[]; warnings: string[];
  derived: {
    offer_count: number | null; unique_seller_count: number | null;
    price_min: number | null; price_max: number | null; lowest_offer: Offer | null;
    best_offers: Offer[] | null; observed_offer_count: number; observed_unique_seller_count: number;
  };
};

function money(value: number | null) {
  return value == null ? "Onbekend" : value.toLocaleString("nl-NL", { style: "currency", currency: "EUR" });
}

function OfferSummary({ offer }: { offer: Offer }) {
  return <span>{money(offer.price)}; verkoper {offer.retailerId ?? "onbekend"};
    {" "}fulfilment: {offer.fulfilmentMethod ?? "onbekend"};
    {" "}levering: {offer.minDeliveryDate ?? "onbekend"} – {offer.maxDeliveryDate ?? "onbekend"};
    {" "}uiterste besteltijd: {offer.ultimateOrderTime ?? "onbekend"}.</span>;
}

export function BolMarket({ market }: { market?: MarketMeasurement }) {
  if (!market) return <p>Geen marktmeting opgeslagen bij deze preview.</p>;
  const complete = market.status === "complete";
  const data = market.derived;
  return <section aria-label="Bol marktmeting">
    <h3>Marktmeting — {market.country} / {market.condition}</h3>
    <p>Bron: {market.source} {market.api_version}. Gemeten: {new Date(market.measured_at).toLocaleString("nl-NL")}.
      {" "}Ouderdom bij weergave: {Math.max(0, Math.floor((Date.now() - Date.parse(market.measured_at)) / 60000))} minuten.</p>
    <p>{complete ? "Alle pagina’s opgehaald en gegevens gevalideerd." :
      market.status === "partial" ? "Gedeeltelijke meting: totalen en volledige prijsrange zijn onbekend." :
        "Marktdata niet beschikbaar. Dit betekent niet dat er geen concurrentie is."}</p>
    <dl className="bol-preview-details">
      <dt>Prijsrange aanbiedingen (ProductRadar-berekening)</dt>
      <dd>{complete && data.price_min != null ? `${money(data.price_min)} – ${money(data.price_max)}` : "Onbekend"}</dd>
      <dt>Unieke verkopers (ProductRadar-telling)</dt><dd>{complete ? data.unique_seller_count ?? "Onbekend" : "Onbekend"}</dd>
      <dt>Aanbiedingen (ProductRadar-telling)</dt><dd>{complete ? data.offer_count ?? "Onbekend" : "Onbekend"}</dd>
      <dt>Laagste aanbieding (ProductRadar-berekening)</dt>
      <dd>{complete && data.lowest_offer ? <OfferSummary offer={data.lowest_offer} /> : "Onbekend / niet beschikbaar"}</dd>
      <dt>Beste aanbieding volgens bol</dt>
      <dd>{complete && data.best_offers?.length ? data.best_offers.map((offer, index) =>
        <p key={offer.offerId ?? index}><OfferSummary offer={offer} /></p>) : "Niet beschikbaar"}</dd>
    </dl>
    {!complete && <p>Alleen waargenomen in ontvangen data: {data.observed_offer_count} aanbiedingen en
      {" "}{data.observed_unique_seller_count} herkenbare unieke verkopers. Dit zijn geen volledige markttotalen.</p>}
    <p>Prijzen, verkoper-ID’s, fulfilment, leverinformatie en de beste-aanbiedingmarkering komen van bol.
      Tellingen, prijsrange en laagste aanbieding zijn door ProductRadar afgeleid. Eén verkoper kan meerdere aanbiedingen hebben.
      Deze meting past handmatige prijzen, Opportunity Score en Decision Engine niet aan.</p>
    <p>Prijzen zijn de door bol geretourneerde aanbiedingsprijzen; er worden geen extra verzendkosten of kortingen bij verzonnen.</p>
    {market.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
    {market.offers.length > 0 && <details>
      <summary>Ontvangen aanbiedingen bekijken (eerste {Math.min(50, market.offers.length)})</summary>
      <ul>{market.offers.slice(0, 50).map((offer, index) => <li key={offer.offerId ?? index}>
        <OfferSummary offer={offer} />{offer.bestOffer === true && " Beste aanbieding volgens bol."}
      </li>)}</ul>
    </details>}
  </section>;
}
