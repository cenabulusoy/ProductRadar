"use client";

import { useEffect, useMemo, useState } from "react";
import { Filters } from "../components/Filters";
import { ProductCard } from "../components/ProductCard";
import { SearchBar } from "../components/SearchBar";
import { TodaysOpportunities } from "../components/TodaysOpportunities";
import {
  defaultFilters,
  filterProducts,
  ProductFilters,
} from "../lib/filters";
import { searchProducts } from "../lib/search";
import { Product } from "../lib/types";

type SortOption =
  | "opportunity"
  | "margin"
  | "revenue"
  | "sales"
  | "sellers";

const API =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export default function Home() {
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState("");
  const [filters, setFilters] =
    useState<ProductFilters>(defaultFilters);
  const [sortBy, setSortBy] =
    useState<SortOption>("opportunity");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState("");

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

  async function importCsv(file: File) {
    setImporting(true);
    setImportMessage("");
    setError("");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API}/products/import`, {
        method: "POST",
        body: formData,
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(
          result.detail ?? "Importeren is mislukt",
        );
      }

      setImportMessage(result.message);
      await loadProducts();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Importeren is mislukt",
      );
    } finally {
      setImporting(false);
    }
  }

  const searchedProducts = useMemo(
    () => searchProducts(products, search),
    [products, search],
  );

  const visibleProducts = useMemo(() => {
    const filtered = filterProducts(searchedProducts, filters);

    return [...filtered].sort((a, b) => {
      switch (sortBy) {
        case "margin":
          return (
            b.analysis.margin_percent -
            a.analysis.margin_percent
          );

        case "revenue":
          return (
            b.analysis.monthly_revenue -
            a.analysis.monthly_revenue
          );

        case "sales":
          return (
            b.analysis.average_monthly_sales -
            a.analysis.average_monthly_sales
          );

        case "sellers":
          return a.sellers - b.sellers;

        case "opportunity":
        default:
          return (
            b.analysis.opportunity_score -
            a.analysis.opportunity_score
          );
      }
    });
  }, [searchedProducts, filters, sortBy]);

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
              SPRINT 2 · PRODUCT IMPORT
            </span>

            <h1>
              Vind producten die de investering waard zijn.
            </h1>

            <p>
              Zoek, filter, sorteer en importeer producten op
              basis van markt-, winst- en risicoscores.
            </p>
          </div>

          <label className="primary">
            {importing ? "Importeren..." : "CSV importeren"}

            <input
              type="file"
              accept=".csv,text/csv"
              hidden
              disabled={importing}
              onChange={(event) => {
                const file = event.target.files?.[0];

                if (file) {
                  void importCsv(file);
                }

                event.target.value = "";
              }}
            />
          </label>
        </header>

        {importMessage && (
          <div className="import-message">
            {importMessage}
          </div>
        )}

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
            <strong>{stats.averageMargin.toFixed(1)}%</strong>
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

        <TodaysOpportunities products={visibleProducts} />

        <div className="hunter-toolbar">
          <SearchBar
            value={search}
            resultCount={visibleProducts.length}
            totalCount={products.length}
            onChange={setSearch}
            onClear={() => setSearch("")}
          />

          <label className="sort-control">
            <span>Sorteren op</span>

            <select
              value={sortBy}
              onChange={(event) =>
                setSortBy(event.target.value as SortOption)
              }
            >
              <option value="opportunity">
                Hoogste Opportunity Score
              </option>
              <option value="margin">
                Hoogste marge
              </option>
              <option value="revenue">
                Hoogste omzet
              </option>
              <option value="sales">
                Meeste verkopen
              </option>
              <option value="sellers">
                Minste aanbieders
              </option>
            </select>
          </label>
        </div>

        {error && (
          <div className="error">
            {error}. Start eerst de FastAPI-backend op poort
            8000.
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
                <strong>
                  Geen passende producten gevonden
                </strong>

                <p>
                  Verlaag één of meer filters of wijzig je
                  zoekopdracht.
                </p>

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
