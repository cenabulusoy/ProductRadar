"use client";

import { useRef, useState } from "react";

type Preview = {
  filename: string;
  product_count: number;
  preview: { name: string; category: string; brand: string; ean: string;
    sale_price: number; purchase_price: number }[];
};

export function CsvImport({ api, onImported }: {
  api: string; onImported: () => Promise<void>;
}) {
  const [pending, setPending] = useState<{ file: File; result: Preview } | null>(null);
  const [phase, setPhase] = useState<"idle" | "preview" | "import">("idle");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const busy = useRef(false);
  const input = useRef<HTMLInputElement>(null);

  async function upload(file: File, preview: boolean) {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(`${api}/products/import${preview ? "/preview" : ""}`, {
      method: "POST", body,
    });
    const result = await response.json().catch(() => null);
    if (!response.ok || !result) {
      throw new Error(typeof result?.detail === "string" ? result.detail :
        "Het bestand kon niet worden verwerkt. Controleer de verbinding met de backend.");
    }
    return result;
  }

  async function preview(file: File) {
    if (busy.current) return;
    busy.current = true;
    setPhase("preview");
    setPending(null);
    setMessage("");
    setError("");
    try {
      const result: Preview = await upload(file, true);
      setPending({ file, result });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voorbeeld laden is mislukt.");
    } finally {
      busy.current = false;
      setPhase("idle");
    }
  }

  async function confirm() {
    if (!pending || busy.current) return;
    busy.current = true;
    setPhase("import");
    setError("");
    try {
      const result = await upload(pending.file, false);
      setPending(null);
      setMessage(result.message);
      await onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Importeren is mislukt.");
    } finally {
      busy.current = false;
      setPhase("idle");
    }
  }

  return <section className="csv-import" aria-label="CSV importeren" aria-busy={phase !== "idle"}>
    <button type="button" className="primary" disabled={phase !== "idle"}
      onClick={() => input.current?.click()}>
      {phase === "preview" ? "Voorbeeld laden…" : "CSV kiezen"}
    </button>
    <input ref={input} type="file" accept=".csv,text/csv" hidden disabled={phase !== "idle"}
      onChange={event => {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (file) void preview(file);
      }} />
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p className="import-message" role="status">{message}</p>}
    {pending && <div className="panel csv-preview">
      <h2>Controleer je CSV vóór import</h2>
      <p><strong>Bestand:</strong> {pending.result.filename}</p>
      <p role="status">{pending.result.product_count} producten gevonden. Er is nog niets geïmporteerd.</p>
      <div className="csv-table-scroll" tabIndex={0} role="region" aria-label="Productvoorbeeld">
        <table>
          <caption>Eerste {pending.result.preview.length} producten</caption>
          <thead><tr>{["Product", "Categorie", "Merk", "EAN", "Verkoopprijs", "Inkoopprijs"].map(
            label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{pending.result.preview.map((product, index) => <tr key={index}>
            <td>{product.name}</td><td>{product.category}</td><td>{product.brand || "—"}</td>
            <td>{product.ean || "—"}</td>
            <td>{product.sale_price.toLocaleString("nl-NL", { style: "currency", currency: "EUR" })}</td>
            <td>{product.purchase_price.toLocaleString("nl-NL", { style: "currency", currency: "EUR" })}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p>Bestaande en dubbele EAN-codes worden bij de import overgeslagen. Producten zonder EAN kunnen opnieuw worden toegevoegd.</p>
      <div className="csv-actions">
        <button type="button" className="primary" disabled={phase !== "idle"} onClick={() => void confirm()}>
          {phase === "import" ? "Importeren…" : "Definitief importeren"}
        </button>
        <button type="button" disabled={phase !== "idle"} onClick={() => {
          setPending(null); setError(""); setMessage("Import geannuleerd. Er zijn geen producten toegevoegd.");
        }}>Annuleren</button>
      </div>
    </div>}
  </section>;
}
