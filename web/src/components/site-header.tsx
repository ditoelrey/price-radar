import Link from "next/link";
import { Radar, Search } from "lucide-react";

import { cn } from "@/lib/utils";

const CATEGORIES = [
  { label: "Патики", href: "/products" },
  { label: "Trail & Outdoor", href: "/products?q=terrex" },
  { label: "Running", href: "/products?q=runner" },
  { label: "Adidas", href: "/products?brand=adidas" },
  { label: "Nike", href: "/products?brand=nike" },
  { label: "Puma", href: "/products?brand=puma" },
  { label: "New Balance", href: "/products?brand=new-balance" },
];

export function SiteHeader({ query }: { query?: string }) {
  return (
    <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Radar className="size-5" />
          </span>
          <span className="text-lg font-semibold tracking-tight">
            price<span className="text-primary">radar</span>
          </span>
        </Link>

        <form action="/products" className="relative mx-auto w-full max-w-xl">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            name="q"
            defaultValue={query}
            placeholder="Пребарај патики, бренд или шифра…"
            aria-label="Search products"
            className={cn(
              "h-10 w-full rounded-full border border-input bg-background pl-9 pr-4 text-sm",
              "placeholder:text-muted-foreground focus-visible:outline-none",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            )}
          />
        </form>

        <span className="hidden shrink-0 text-xs text-muted-foreground lg:block">
          7 shops · North Macedonia
        </span>
      </div>

      <nav className="border-t">
        <div className="mx-auto flex max-w-7xl items-center gap-1 overflow-x-auto px-4 py-1.5 sm:px-6">
          {CATEGORIES.map((c) => (
            <Link
              key={c.label}
              href={c.href}
              className="whitespace-nowrap rounded-md px-2.5 py-1 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {c.label}
            </Link>
          ))}
        </div>
      </nav>
    </header>
  );
}
