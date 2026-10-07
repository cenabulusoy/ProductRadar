import "./globals.css";

export const metadata = {
  title: "ProductRadar",
  description: "Product research voor slimme inkoopbeslissingen",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="nl">
      <body><nav aria-label="ProductRadar"><a href="/">Product Hunter</a> · <a href="/discovery">Product Discovery</a></nav>{children}</body>
    </html>
  );
}
