"use client";

import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";

import { cn } from "@/lib/utils";

const PLACEHOLDER = "Пронајди ја најдобрата понуда…";

/** One field, two headers. The markup is shared so they cannot drift. */
function SearchField({
  query,
  inputRef,
  autoFocus,
}: {
  query?: string;
  inputRef?: React.Ref<HTMLInputElement>;
  autoFocus?: boolean;
}) {
  return (
    <>
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
        ref={inputRef}
        type="search"
        name="q"
        defaultValue={query}
        placeholder={PLACEHOLDER}
        aria-label="Пребарај производи"
        autoFocus={autoFocus}
        className={cn(
          "h-10 w-full rounded-full border border-input bg-background pl-9 pr-4 text-sm",
          "placeholder:text-muted-foreground focus-visible:outline-none",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        )}
      />
    </>
  );
}

/**
 * The search box, which is a field on a desktop and a button on a phone.
 *
 * At 375px the header has to hold a menu button, the wordmark and the
 * search, and a field wide enough to type a product name into leaves no
 * room for the first two. Every shop here solves it the same way -- a
 * magnifier that opens the field over the page -- so that is what this
 * does: the top row stays the brand and one icon, and the field drops
 * below it when asked for.
 *
 * The desktop field is not the same element moved. Both are rendered and
 * CSS picks one, so the server sends a working form either way and nothing
 * depends on JavaScript having run to be searchable.
 */
export function HeaderSearch({ query }: { query?: string }) {
  const [open, setOpen] = useState(false);
  const field = useRef<HTMLInputElement>(null);

  // Opened by a tap, so the keyboard should already be up by the time the
  // field lands: nobody taps a magnifier to look at an empty box.
  useEffect(() => {
    if (open) field.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <form
        action="/products"
        className="relative mx-auto hidden w-full max-w-2xl sm:block"
      >
        <SearchField query={query} />
      </form>

      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-label="Пребарај"
        aria-expanded={open}
        className={cn(
          "ml-auto grid size-10 shrink-0 place-items-center rounded-full border border-input",
          "text-muted-foreground transition-colors hover:text-foreground sm:hidden",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          open && "border-primary text-primary",
        )}
      >
        {open ? <X className="size-4" /> : <Search className="size-4" />}
      </button>

      {/* Below the row rather than inside it: swapping the logo out for the
          field would make the header flicker between two layouts on every
          tap, and leave a shopper looking at a page with no name on it. */}
      {open && (
        <div className="absolute inset-x-0 top-full border-b bg-background p-3 shadow-sm sm:hidden">
          <form action="/products" className="relative">
            <SearchField query={query} inputRef={field} autoFocus />
          </form>
        </div>
      )}
    </>
  );
}
