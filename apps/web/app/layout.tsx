import type { Metadata } from "next";
import "./../styles.css";

export const metadata: Metadata = {
  title: "VEGA // Vegetation Intelligence",
  description: "Мониторинг вегетации: спутник -> ряд -> ML -> аномалия -> объяснение",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" data-theme="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
