"use client";

import { useEffect, useMemo, useState } from "react";
import { ProductCard } from "../components/ProductCard";
import { Product } from "../lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export default function Home() {
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadProducts() {
    try {
      setError("");
      const response = await fetch(`${API}/products?search=${encodeURIComponent(search)}`, { cache: "no-store" });
      if (!response.ok) throw new Error("Backend niet bereikbaar");
      setProducts(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Onbekende fout");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadProducts(); }, []);

  async function toggleFavorite(id: number) {
    await fetch(`${API}/products/${id}/favorite`, { method: "POST" });
    await loadProducts();
  }

  const stats = useMemo(() => {
    const opportunities = products.filter((p) => p.analysis.opportunity_score >= 65).length;
    const averageMargin = products.length ? products.reduce((sum, p) => sum + p.analysis.margin_percent, 0) / products.length : 0;
    const revenue = products.reduce((sum, p) => sum + p.analysis.monthly_revenue, 0);
    return { opportunities, averageMargin, revenue };
  }, [products]);

  return (
    <main>
      <aside>
        <div className="brand"><div className="logo">PR</div><div><strong>ProductRadar</strong><span>Research OS</span></div></div>
        <nav><a className="active">Dashboard</a><a>Product Hunter</a><a>Vergelijken</a><a>Projecten</a><a>Instellingen</a></nav>
        <div className="sidebar-note">Datastatus<br/><strong>Handmatige testdata</strong></div>
      </aside>
      <section className="content">
        <header><div><span className="eyebrow">SPRINT 1 · FOUNDATION</span><h1>Vind producten die de investering waard zijn.</h1><p>Transparante markt-, winst- en risicoscores zonder schijnprecisie.</p></div><button className="primary">+ Product toevoegen</button></header>
        <div className="stats">
          <div><span>Producten</span><strong>{products.length}</strong></div>
          <div><span>Kansrijk</span><strong>{stats.opportunities}</strong></div>
          <div><span>Gem. marge</span><strong>{stats.averageMargin.toFixed(1)}%</strong></div>
          <div><span>Potentiële omzet</span><strong>€{stats.revenue.toLocaleString("nl-NL", { maximumFractionDigits: 0 })}</strong></div>
        </div>
        <div className="toolbar">
          <input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && loadProducts()} placeholder="Zoek op product, merk of EAN..." />
          <button onClick={loadProducts}>Analyseren</button>
        </div>
        {error && <div className="error">{error}. Start eerst de FastAPI-backend op poort 8000.</div>}
        {loading ? <p>Laden…</p> : <div className="grid">{products.map((p) => <ProductCard key={p.id} product={p} onFavorite={toggleFavorite} />)}</div>}
      </section>
    </main>
  );
}
