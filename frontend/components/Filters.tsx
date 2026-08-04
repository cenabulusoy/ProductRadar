import { ProductFilters } from "../lib/filters";

type Props = {
  filters: ProductFilters;
  categories: string[];
  onChange: (filters: ProductFilters) => void;
  onReset: () => void;
};

export function Filters({
  filters,
  categories,
  onChange,
  onReset,
}: Props) {
  function update<K extends keyof ProductFilters>(
    key: K,
    value: ProductFilters[K],
  ) {
    onChange({
      ...filters,
      [key]: value,
    });
  }

  return (
    <aside className="filter-panel">
      <div className="filter-heading">
        <div>
          <span className="eyebrow">PRODUCT HUNTER</span>
          <h2>Filters</h2>
        </div>

        <button type="button" onClick={onReset}>
          Wissen
        </button>
      </div>

      <label className="filter-field">
        <span>
          Minimale score
          <strong>{filters.minimumScore}</strong>
        </span>

        <input
          type="range"
          min="0"
          max="100"
          step="5"
          value={filters.minimumScore}
          onChange={(event) =>
            update("minimumScore", Number(event.target.value))
          }
        />
      </label>

      <label className="filter-field">
        <span>
          Minimale marge
          <strong>{filters.minimumMargin}%</strong>
        </span>

        <input
          type="range"
          min="-20"
          max="70"
          step="5"
          value={filters.minimumMargin}
          onChange={(event) =>
            update("minimumMargin", Number(event.target.value))
          }
        />
      </label>

      <label className="filter-field">
        <span>
          Maximaal aanbieders
          <strong>{filters.maximumSellers}</strong>
        </span>

        <input
          type="range"
          min="1"
          max="100"
          value={filters.maximumSellers}
          onChange={(event) =>
            update("maximumSellers", Number(event.target.value))
          }
        />
      </label>

      <label className="filter-field">
        <span>Categorie</span>

        <select
          value={filters.category}
          onChange={(event) =>
            update("category", event.target.value)
          }
        >
          <option>Alle categorieën</option>

          {categories.map((category) => (
            <option key={category}>{category}</option>
          ))}
        </select>
      </label>

      <label className="filter-checkbox">
        <input
          type="checkbox"
          checked={filters.favoritesOnly}
          onChange={(event) =>
            update("favoritesOnly", event.target.checked)
          }
        />

        <span>Alleen favorieten</span>
      </label>
    </aside>
  );
}
