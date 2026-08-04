type Props = {
  value: string;
  resultCount: number;
  totalCount: number;
  onChange: (value: string) => void;
  onClear: () => void;
};

export function SearchBar({
  value,
  resultCount,
  totalCount,
  onChange,
  onClear,
}: Props) {
  return (
    <div className="search-bar">
      <div className="search-input-wrap">
        <span aria-hidden="true">⌕</span>

        <input
          type="search"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Zoek op product, merk of categorie..."
          aria-label="Producten zoeken"
        />

        {value && (
          <button
            type="button"
            className="search-clear"
            onClick={onClear}
            aria-label="Zoekopdracht wissen"
          >
            ×
          </button>
        )}
      </div>

      <span className="search-result-count">
        {resultCount} van {totalCount} producten
      </span>
    </div>
  );
}

