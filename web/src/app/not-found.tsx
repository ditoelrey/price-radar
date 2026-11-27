import Link from "next/link";
import { SearchX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

export const metadata = {
  title: "Страницата не е пронајдена",
};

/**
 * The 404, in Macedonian and inside the site.
 *
 * Next ships its own, which reads "404 — This page could not be found." on a
 * bare white page with no header, no search box and no way back. It is the
 * one page a shopper reaches by accident -- a stale link, a product that
 * stopped being carried, a mistyped address -- and it was the only English
 * left on the site after everything else was translated.
 *
 * The header comes with it, so the search box and the four verticals are
 * right there: the useful thing to offer someone who did not find what they
 * typed is the way to look for it again.
 */
export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-4 py-20 text-center sm:px-6">
        <SearchX className="mb-4 size-10 text-muted-foreground/50" />
        <p className="text-sm font-medium text-muted-foreground">404</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">
          Страницата не е пронајдена
        </h1>
        <p className="mt-2 max-w-md text-sm text-muted-foreground">
          Линкот можеби е стар или производот веќе не се продава во ниту една
          од продавниците што ги следиме.
        </p>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <Button asChild>
            <Link href="/">Назад на почетна</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/products?kind=all">Разгледај ги производите</Link>
          </Button>
        </div>
      </main>

      <SiteFooter />
    </div>
  );
}
