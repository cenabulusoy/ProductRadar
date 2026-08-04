"use client";

import { useEffect, useMemo, useState } from "react";
import { ProductCard } from "../components/ProductCard";
import { SearchBar } from "../components/SearchBar";
import { searchProducts } from "../lib/search";
import { Product } from "../lib/types";
import { Filters } from "../components/Filters";
import {
  defaultFilters,
  filterProducts,
  ProductFilters,
} from "../lib/filters";

const API =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export default function Home() {
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState("");
  const [filters, setFilters] =
  useState<ProductFilters>(defaultFilters);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadProducts() {
    try {
      setError("");

      const response = await fetch(`${API}/products`, {
        cache: "no-store",
      });

      if (!response.ok) {
        throw new Error("Backend niet bereikbaar");
      }

      setProducts(await response.json());
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Onbekende fout",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProducts();
  }, []);

  async function toggleFavorite(id: number) {
    await fetch(`${API}/products/${id}/favorite`, {
      method: "POST",
    });

    await loadProducts();
  }

const searchedProducts = useMemo(
  () => searchProducts(products, search),
  [products, search],
);

const visibleProducts = useMemo(
  () => filterProducts(searchedProducts, filters),
  [searchedProducts, filters],
);

const categories = useMemo(
  () =>
    Array.from(
      new Set(products.map((product) => product.category)),
    ).sort(),
  [products],
);

  const stats = useMemo(() => {
    const opportunities = visibleProducts.filter(
      (product) => product.analysis.opportunity_score >= 65,
    ).length;

    const averageMargin = visibleProducts.length
      ? visibleProducts.reduce(
          (sum, product) =>
            sum + product.analysis.margin_percent,
          0,
        ) / visibleProducts.length
      : 0;

    const revenue = visibleProducts.reduce(
      (sum, product) =>
        sum + product.analysis.monthly_revenue,
      0,
    );

    return {
      opportunities,
      averageMargin,
      revenue,
    };
  }, [visibleProducts]);

  return (
    <main>
      <aside>
        <div className="brand">
          <div className="logo">PR</div>

          <div>
            <strong>ProductRadar</strong>
            <span>Research OS</span>
          </div>
        </div>

        <nav>
          <a className="active">Dashboard</a>
          <a>Product Hunter</a>
          <a>Vergelijken</a>
          <a>Projecten</a>
          <a>Instellingen</a>
        </nav>

        <div className="sidebar-note">
          Datastatus
          <br />
          <strong>Handmatige testdata</strong>
        </div>
      </aside>

      <section className="content">
        <header>
          <div>
            <span className="eyebrow">
              SPRINT 1 · PRODUCT HUNTER
            </span>

            <h1>
              Vind producten die de investering waard zijn.
            </h1>

            <p>
              Zoek direct op product, merk of categorie en
              vergelijk kansen zonder nieuwe API-aanvraag.
            </p>
          </div>

          <button className="primary">
            + Product toevoegen
          </button>
        </header>

        <div className="stats">
          <div>
            <span>Producten</span>
            <strong>{visibleProducts.length}</strong>
          </div>

          <div>
            <span>Kansrijk</span>
            <strong>{stats.opportunities}</strong>
          </div>

          <div>
            <span>Gem. marge</span>
            <strong>
              {stats.averageMargin.toFixed(1)}%
            </strong>
          </div>

          <div>
            <span>Potentiële omzet</span>
            <strong>
              €
              {stats.revenue.toLocaleString("nl-NL", {
                maximumFractionDigits: 0,
              })}
            </strong>
          </div>
        </div>

        <SearchBar
          value={search}
          resultCount={visibleProducts.length}
          totalCount={products.length}
          onChange={setSearch}
          onClear={() => setSearch("")}
        />

        {error && (
          <div className="error">
            {error}. Start eerst de FastAPI-backend op
            poort 8000.
          </div>
        )}

<div className="hunter-layout">
  <Filters
    filters={filters}
    categories={categories}
    onChange={setFilters}
    onReset={() => setFilters(defaultFilters)}
  />

  <div className="hunter-results">
    {loading ? (
      <p>Laden…</p>
    ) : visibleProducts.length ? (
      <div className="grid">
        {visibleProducts.map((product) => (
          <ProductCard
            key={product.id}
            product={product}
            onFavorite={toggleFavorite}
          />
        ))}
      </div>
    ) : (
      <div className="empty-state panel">
        <strong>Geen passende producten gevonden</strong>
        <p>Verlaag één of meer filters.</p>

        <button
          type="button"
          onClick={() => {
            setSearch("");
            setFilters(defaultFilters);
          }}
        >
          Alle filters wissen
        </button>
      </div>
    )}
  </div>
</div>
        
      </section>
    </main>
  );
}
