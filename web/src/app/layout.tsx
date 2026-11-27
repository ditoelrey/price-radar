import type { Metadata } from "next";
import { Inter } from "next/font/google";

import "./globals.css";

const inter = Inter({
  subsets: ["latin", "cyrillic"],
  display: "swap",
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: {
    default: "Price Radar — спореди цени на патики во Македонија",
    template: "%s · Price Radar",
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
