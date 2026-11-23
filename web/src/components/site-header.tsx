import Link from "next/link";
import { Radar, Search } from "lucide-react";

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

        <Link href="/" className="flex shrink-0 items-center gap-2">
          <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Radar className="size-5" />
          </span>
          <span className="hidden text-lg font-semibold tracking-tight sm:inline">
            price<span className="text-primary">radar</span>
          </span>
        </Link>

        <form action="/products" className="relative mx-auto w-full max-w-2xl">
          {/* Search spans the whole catalogue, and has to say so.
              The API defaults an absent `kind` to footwear -- the right
              default for a listing, since the shops it crawls also sell
              socks and ski leggings -- but the wrong one for a search box.
              Without this the box answered "Versace" with shoes only and
              claimed the four fragrance verticals did not exist; the same
              silence hid облека and опрема before them. */}
          <input type="hidden" name="kind" value="all" />
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            name="q"
            defaultValue={query}
            placeholder="Пребарај производ, бренд или шифра…"
            aria-label="Пребарај производи"
            className={cn(
              "h-10 w-full rounded-full border border-input bg-background pl-9 pr-4 text-sm",
              "placeholder:text-muted-foreground focus-visible:outline-none",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            )}
          />
        </form>

        <span className="hidden shrink-0 text-xs text-muted-foreground lg:block">
          6 продавници · Македонија
        </span>
      </div>

      <MainNav activeKind={activeKind} />
    </header>
  );
}
