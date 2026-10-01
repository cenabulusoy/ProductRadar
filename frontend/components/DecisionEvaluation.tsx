"use client";
import { useEffect, useRef, useState } from "react";
import type { Evaluation } from "../lib/comparison-types";
import { ProvenanceLegend, score } from "./DecisionComparison";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
export function DecisionEvaluation({ api = API }: { api?: string }) {
  const [data, setData] = useState<Evaluation | null>(null), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const requestId = useRef(0);
  useEffect(() => () => { requestId.current++; }, [api]);
  async function load(offset = 0) {
    const current = ++requestId.current;
    setLoading(true); setError(""); setData(null);
    try {
      const response = await fetch(`${api}/comparison/products?offset=${offset}&limit=25`, { cache: "no-store" });
      if (!response.ok) throw new Error();
      const body = await response.json();
      if (!Array.isArray(body.items)) throw new Error();
      if (current === requestId.current) setData(body);
    } catch { if (current === requestId.current) setError("Evaluatie niet beschikbaar. Probeer opnieuw."); }
    finally { if (current === requestId.current) setLoading(false); }
  }
  return <section className="panel comparison-panel"><h1>V1 versus v2 · evaluatiemodus</h1>
    <p>V1 blijft de standaard voor het dashboard. Dit overzicht gebruikt opgeslagen producten en metingen, in productvolgorde. Er wordt niets opgeslagen of bij bol opgehaald.</p>
    <button type="button" onClick={() => load()} disabled={loading}>{loading ? "Evaluatie laden…" : "Vergelijk bestaande producten"}</button>
    {error && <p role="alert">{error}</p>}
    {data && <><p role="status">{data.total} opgeslagen producten · Analyse: {data.evaluated_at}</p>
      {!data.items.length ? <p>Geen opgeslagen producten op deze pagina.</p> : <div className="comparison-table-wrap"><table className="comparison-table"><caption>V1 en v2 naast elkaar — geen v2-rangschikking</caption><thead><tr><th scope="col">Product</th><th scope="col">V1 score / verdict</th><th scope="col">V2 score / verdict</th><th scope="col">Data Confidence v2</th><th scope="col">Belangrijkste reden</th></tr></thead>
        <tbody>{data.items.map(item => <tr key={item.product.id}><th scope="row"><a href={`/products/${item.product.id}`}>{item.product.name}</a></th>{"error" in item ? <td colSpan={4}>{item.error}</td> : <>
          <td>{score(item.analysis_v1.opportunity_score)}<br />{item.analysis_v1.verdict}</td><td>{score(item.analysis_v2.opportunity_score)}<br />{item.analysis_v2.verdict}{item.analysis_v2.opportunity_score == null && <small>Geen definitieve actuele score</small>}</td>
          <td>{score(item.analysis_v2.subscores.data_confidence)}</td><td>{item.primary_reason.text}</td></>}</tr>)}</tbody>
      </table></div>}
      <div className="comparison-pagination"><button type="button" disabled={loading || data.offset === 0} onClick={() => load(Math.max(0, data.offset - data.limit))}>Vorige pagina</button><button type="button" disabled={loading || data.next_offset == null} onClick={() => load(data.next_offset!)}>Volgende pagina</button></div>
    </>}
    <ProvenanceLegend />
  </section>;
}
