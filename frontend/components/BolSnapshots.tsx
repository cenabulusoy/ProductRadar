"use client";

import { BolMarket, MarketMeasurement } from "./BolMarket";

import { useRef, useState } from "react";

type Snapshot = {
  id: number; saved_at: string;
  preview: {
    market?: MarketMeasurement;
    ean: string; source: string; api_version: string; fetched_at: string;
    status: string; bol_product_id: string | null;
    catalog: { title: string | null };
    ratings: { count: number; average: number | null } | null;
    warnings: string[];
  };
};

export function BolSnapshots({ api, ean, previewId }: { api: string; ean: string; previewId?: string }) {
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const [saved, setSaved] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);

  async function request(save: boolean) {
    if (locked.current || (save && (saved || !previewId))) return;
    locked.current = true;
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await fetch(save ? `${api}/bol/snapshots` : `${api}/bol/products/${ean}/snapshots`,
        save ? { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ preview_id: previewId }), cache: "no-store" } : { cache: "no-store" });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result) throw new Error(typeof result?.detail === "string" ? result.detail : "Snapshots zijn tijdelijk niet beschikbaar.");
      if (save) {
        setSaved(true); setSnapshots([result]);
        setMessage("Snapshot opgeslagen. Handmatige velden, CSV-data en scores zijn ongewijzigd.");
      } else {
        setSnapshots(result.snapshots);
        setMessage(result.snapshots.length ? "Opgeslagen metingen (maximaal 50, nieuwste meting eerst)." : "Nog geen snapshots voor deze EAN.");
      }
    } catch (err) {
      setError(err instanceof TypeError ? "De backend is niet bereikbaar. Probeer het opnieuw." :
        err instanceof Error ? err.message : "Snapshots zijn tijdelijk niet beschikbaar.");
    } finally { locked.current = false; setBusy(false); }
  }

  if (!/^[0-9]{13}$/.test(ean)) return null;
  return <section aria-label="Bol snapshots" aria-busy={busy}>
    <h3>Bronmetingen</h3>
    <p>Een snapshot bewaart deze bol-meting apart. Prijzen, CSV-data en Decision Engine-scores worden niet aangepast.</p>
    {previewId && <button type="button" disabled={busy || saved} onClick={() => request(true)}>
      {saved ? "Snapshot opgeslagen" : "Deze preview als snapshot opslaan"}
    </button>}
    <button type="button" disabled={busy} onClick={() => request(false)}>Opgeslagen snapshots bekijken</button>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <ul>{snapshots.map(snapshot => <li key={snapshot.id}>
      <strong>{snapshot.preview.catalog.title ?? snapshot.preview.ean}</strong>
      <p>Bron: {snapshot.preview.source}. Gemeten: {new Date(snapshot.preview.fetched_at).toLocaleString("nl-NL")}.
        {" "}Ouderdom bij weergave: {Math.max(0, Math.floor((Date.now() - Date.parse(snapshot.preview.fetched_at)) / 60000))} minuten.
        {" "}Opgeslagen: {new Date(snapshot.saved_at).toLocaleString("nl-NL")}.</p>
      <p>{snapshot.preview.status === "complete" ? "Bronnen van deze meting opgehaald" : "Gedeeltelijke meting"}.
        {" "}Bol-product-ID: {snapshot.preview.bol_product_id ?? "Niet beschikbaar"}.</p>
      <p>Beoordelingen: {snapshot.preview.ratings?.count ?? "Niet beschikbaar"};
        {" "}gemiddelde: {snapshot.preview.ratings?.average ?? "Niet beschikbaar"} (berekend uit bol-sterrenverdeling).</p>
      <BolMarket market={snapshot.preview.market} />
      {snapshot.preview.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
    </li>)}</ul>
  </section>;
}
