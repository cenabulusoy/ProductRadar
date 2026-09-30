"use client";

import { FormEvent, useRef, useState } from "react";

type Preview = {
  ean: string; source: string; fetched_at: string; language: string;
  catalog: { title: string | null; brand: string | null; classification_id: string | null;
    published: boolean | null; enrichment: number | null };
  ratings: { count: number; average: number | null; distribution: { rating: number; count: number }[] } | null;
  warnings: string[];
};

export function BolEanPreview({ api }: { api: string }) {
  const [ean, setEan] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const busy = useRef(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    setPreview(null);
    setError("");
    if (!/^[0-9]{13}$/.test(ean)) {
      setError("Voer een EAN van precies 13 cijfers in.");
      return;
    }
    busy.current = true;
    setLoading(true);
    try {
      const response = await fetch(`${api}/bol/ean-preview/${encodeURIComponent(ean)}`, { cache: "no-store" });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result) {
        throw new Error(typeof result?.detail === "string" ? result.detail : "De bol-preview kon niet worden geladen.");
      }
      setPreview(result);
    } catch (err) {
      setError(err instanceof TypeError ? "De backend is niet bereikbaar. Probeer het later opnieuw." :
        err instanceof Error ? err.message : "De bol-preview kon niet worden geladen.");
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }

  return <section className="panel bol-preview" aria-label="Bol EAN-preview" aria-busy={loading}>
    <h2>Product bekijken bij bol</h2>
    <p>Alleen een voorbeeld: je producten, CSV-import en scores blijven ongewijzigd.</p>
    <form onSubmit={submit} className="bol-preview-form">
      <label htmlFor="bol-ean">EAN (13 cijfers)</label>
      <input id="bol-ean" type="text" inputMode="numeric" autoComplete="off" maxLength={13}
        value={ean} disabled={loading} onChange={event => {
          setEan(event.target.value.trim()); setPreview(null); setError("");
        }} />
      <button type="submit" className="primary" disabled={loading}>
        {loading ? "Ophalen…" : "Voorbeeld ophalen"}
      </button>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    {preview && <div>
      <p role="status">Gegevens opgehaald voor {preview.ean}. Er is niets opgeslagen.</p>
      <dl className="bol-preview-details">
        <dt>Product</dt><dd>{preview.catalog.title ?? "Niet beschikbaar"}</dd>
        <dt>Merk</dt><dd>{preview.catalog.brand ?? "Niet beschikbaar"}</dd>
        <dt>Catalogusclassificatie</dt><dd>{preview.catalog.classification_id ?? "Niet beschikbaar"}</dd>
        <dt>Content voldoet aan publicatie-eisen</dt>
        <dd>{preview.catalog.published === null ? "Onbekend" : preview.catalog.published ? "Ja" : "Nee"} — dit zegt niets over voorraad.</dd>
        <dt>Aantal beoordelingen</dt><dd>{preview.ratings?.count ?? "Niet beschikbaar"}</dd>
        <dt>Gemiddelde beoordeling</dt><dd>{preview.ratings?.average == null ? "Niet beschikbaar" : `${preview.ratings.average.toLocaleString("nl-NL")} / 5`}</dd>
      </dl>
      <p>Bron: {preview.source}. Opgehaald: {new Date(preview.fetched_at).toLocaleString("nl-NL")}.</p>
      <p>Aantal en gemiddelde zijn berekend uit de sterrenverdeling van bol. Dit zijn geen verkoopaantallen.</p>
      {preview.warnings.map((warning, index) => <p role="alert" key={index}>{warning}</p>)}
    </div>}
  </section>;
}
