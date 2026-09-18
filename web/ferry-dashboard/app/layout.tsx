import type { Metadata } from "next";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Bengkalis–Pakning Ferry Operations",
  description: "Realtime ETA–ETD monitoring Bengkalis–Pakning",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({children}:{children:React.ReactNode}) {
  return (
    <html lang="id" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
