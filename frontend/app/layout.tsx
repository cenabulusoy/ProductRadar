import "./globals.css";

export const metadata = {
  title: "ProductRadar",
  description: "Product research voor slimme inkoopbeslissingen",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="nl">
      <body>{children}</body>
    </html>
  );
}
