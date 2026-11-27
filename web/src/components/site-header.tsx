import Link from "next/link";

import { HeaderSearch } from "@/components/header-search";
import { BRAND_DOMAIN, Logo } from "@/components/logo";

import { MainNav } from "@/components/nav/main-nav";
import { MobileNav } from "@/components/nav/mobile-nav";
import { cn } from "@/lib/utils";

/**
 * Two rows: identity and search on top, the product verticals below.
 *
 * The split is not decoration. Search is how someone who knows what they
 * want arrives, and browsing is how someone who does not does -- putting
 * them on one line makes the narrower one fight for width on every screen.
 *
 * What is deliberately absent from the nav row: brands and discounts. Both
 * are filters on a listing, not verticals, and a nav bar that mixes the two
 * stops saying anything about the shape of the catalogue.
 */
export function SiteHeader({
  query,
  activeKind,
}: {
  query?: string;
  activeKind?: string;
}) {
  return (
    <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="relative mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:gap-4 sm:px-6">
        <MobileNav />

        <Link
          href="/"
          aria-label={BRAND_DOMAIN}
          className="shrink-0 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Logo />
        </Link>

        <HeaderSearch query={query} />

        <span className="hidden shrink-0 text-xs text-muted-foreground lg:block">
          6 продавници · Македонија
        </span>
      </div>

      <MainNav activeKind={activeKind} />
    </header>
  );
}
