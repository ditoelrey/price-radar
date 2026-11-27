import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { BRAND_DOMAIN, SITE_TAGLINE } from "@/components/logo";

import "./globals.css";

const inter = Inter({
  subsets: ["latin", "cyrillic"],
  display: "swap",
  variable: "--font-sans",
});

export const metadata: Metadata = {
  // Read from the one constant the logo reads, so the tab and the
  // wordmark cannot disagree while the name is still being chosen.
  title: {
    default: `${BRAND_DOMAIN} — ${SITE_TAGLINE}`,
    template: `%s · ${BRAND_DOMAIN}`,
  },
  description:
    "Спореди ги цените на спортската опрема, обувките и парфемите во македонските продавници. Еден производ, сите достапни понуди, подредени од најниска кон највисоката цена.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="mk" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans`}>{children}</body>
    </html>
  );
}
