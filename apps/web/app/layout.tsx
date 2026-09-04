import type { Metadata } from "next";
import "./../styles.css";

export const metadata: Metadata = {
  title: "VEGA // Vegetation Intelligence",
  description: "Мониторинг вегетации: спутник -> ряд -> ML -> аномалия -> объяснение",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" data-theme="dark">
      <body>{children}</body>
    </html>
  );
}
