import { ProductDetail } from "../../../components/ProductDetail";
import { Product } from "../../../lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

async function getProduct(id: string): Promise<Product> {
  const response = await fetch(`${API}/products/${id}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Product niet gevonden");
  return response.json();
}

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const product = await getProduct(id);
  return <ProductDetail product={product} />;
}
