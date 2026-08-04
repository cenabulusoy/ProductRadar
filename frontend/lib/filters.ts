import { Product } from "./types";

export type ProductFilters = {
  minimumScore: number;
  minimumMargin: number;
  maximumSellers: number;
  category: string;
  favoritesOnly: boolean;
};

export const defaultFilters: ProductFilters = {
  minimumScore: 0,
  minimumMargin: 0,
  maximumSellers: 100,
  category: "Alle categorieën",
  favoritesOnly: false,
};

export function filterProducts(
  products: Product[],
  filters: ProductFilters,
): Product[] {
  return products.filter((product) => {
    const matchesScore =
      product.analysis.opportunity_score >= filters.minimumScore;

    const matchesMargin =
      product.analysis.margin_percent >= filters.minimumMargin;

    const matchesSellers =
      product.sellers <= filters.maximumSellers;

    const matchesCategory =
      filters.category === "Alle categorieën" ||
      product.category === filters.category;

    const matchesFavorite =
      !filters.favoritesOnly || product.favorite;

    return (
      matchesScore &&
      matchesMargin &&
      matchesSellers &&
      matchesCategory &&
      matchesFavorite
    );
  });
}
