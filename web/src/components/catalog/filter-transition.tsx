"use client";

import {
  createContext,
  useCallback,
  useContext,
  useOptimistic,
  useTransition,
  type MouseEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { type GroupKey } from "@/lib/filters";
import { cn } from "@/lib/utils";

/**
 * The second between a click and the new prices.
 *
 * Every control on this page is a link, and the page behind it is rendered
 * on the server -- which is what makes a filtered listing a real URL, and
 * what costs about a second per click. Next navigates when the new page is
 * ready, so until then nothing on screen changes at all: the box a shopper
 * ticked does not tick, the count does not move, and the honest reading is
 * that the click did not land. People click again.
 *
 * `useTransition` is what closes that gap. The navigation is started inside
 * one, so React hands back a `pending` flag for exactly as long as the
 * server is working, and the page can say so. Nothing is faked: the cards do
 * not change until the real ones arrive, because a filter changes what the
 * prices *mean* and showing stale figures as though they were the answer is
 * the one thing this site must not do.
 *
 * The links stay links. A plain left click is intercepted; a middle click, a
 * modified click and a right click are left alone, so "open in new tab"
 * still works and a crawler still sees an href.
 */
/**
 * What the click is about to do to one box, before the server agrees.
 *
 * The prices cannot be guessed -- that is the whole job of this site -- but
 * the tick can: clicking a checkbox has exactly one meaning, and the shopper
 * already knows it. So the box answers in the frame they clicked it, and the
 * cards go on saying what they honestly still say until the new ones arrive.
 */
export type OptimisticPick = {
  group: GroupKey;
  value: string;
  /** What this option's state becomes. */
  selected: boolean;
};

type Transition = {
  pending: boolean;
  pick: OptimisticPick | null;
  navigate: (href: string, pick?: OptimisticPick) => void;
};

const FilterTransitionContext = createContext<Transition | null>(null);

export function FilterTransitionProvider({
  children,
}: {
  children: ReactNode;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  // `useOptimistic` rather than a piece of state we would have to clear:
  // React drops the optimistic value when the transition it was set in
  // finishes, which is exactly the moment the server's own answer lands. A
  // `useState` here would leave the guess on screen for a frame after the
  // truth arrived, and that frame is where a wrong tick would show.
  const [pick, setPick] = useOptimistic<OptimisticPick | null, OptimisticPick | null>(
    null,
    (_, next) => next,
  );

  const navigate = useCallback(
    (href: string, next?: OptimisticPick) => {
      // `scroll: false` throughout: ticking a box on a listing is not
      // arriving at a new page, and being thrown to the top each time makes
      // the sidebar unusable.
      startTransition(() => {
        if (next) setPick(next);
        router.push(href, { scroll: false });
      });
    },
    [router, setPick],
  );

  return (
    <FilterTransitionContext.Provider value={{ pending, pick, navigate }}>
      {children}
    </FilterTransitionContext.Provider>
  );
}

/**
 * The transition, or null outside the provider.
 *
 * Null is a working state, not an error: a control rendered outside a
 * listing page navigates the ordinary way.
 */
export function useFilterTransition(): Transition | null {
  return useContext(FilterTransitionContext);
}

/** True while a filter navigation is in flight. */
export function useFilterPending(): boolean {
  return useContext(FilterTransitionContext)?.pending ?? false;
}

/**
 * This option's state, with the click that has not landed yet applied.
 *
 * Three cases. The option that was clicked shows what the click makes it. In
 * a single-select group, every other option shows unselected the moment one
 * of them is picked, because that is what picking one means. Everything else
 * shows what the server last said.
 */
export function useOptimisticSelected(
  group: GroupKey,
  value: string,
  selected: boolean,
  single?: boolean,
): boolean {
  const pick = useContext(FilterTransitionContext)?.pick ?? null;
  if (pick === null || pick.group !== group) return selected;
  if (pick.value === value) return pick.selected;
  return single && pick.selected ? false : selected;
}

/**
 * A `<Link>` that reports its own navigation as pending.
 *
 * Used by every filter control, so one click anywhere -- a checkbox, a chip,
 * a size, a page number -- lights the same indicator.
 */
export function FilterLink({
  href,
  children,
  className,
  onNavigate,
  pick,
  ...rest
}: {
  href: string;
  children: ReactNode;
  className?: string;
  /** Run after the navigation starts: the mobile sort sheet closes itself. */
  onNavigate?: () => void;
  /** What this click does to its own box, shown before the server answers. */
  pick?: OptimisticPick;
} & Omit<React.ComponentProps<typeof Link>, "href" | "onClick">) {
  const transition = useFilterTransition();

  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    // Everything that is not a plain left click belongs to the browser.
    if (
      transition === null ||
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      onNavigate?.();
      return;
    }
    event.preventDefault();
    transition.navigate(href, pick);
    onNavigate?.();
  };

  return (
    <Link href={href} scroll={false} onClick={onClick} className={className} {...rest}>
      {children}
    </Link>
  );
}

/**
 * The grid while the next one is being built.
 *
 * Dimmed and desaturated rather than replaced: the cards on screen are still
 * the answer to the previous question, and a shopper comparing two of them
 * should not lose the page to a skeleton. Pointer events go off with it, so a
 * price that is about to change cannot be clicked through by accident -- the
 * one failure mode that would actually cost someone money.
 */
export function PendingGrid({ children }: { children: ReactNode }) {
  const pending = useFilterPending();

  return (
    <div className="relative">
      <div
        aria-busy={pending}
        className={cn(
          "transition-[opacity,filter] duration-200",
          pending && "pointer-events-none opacity-50 grayscale",
        )}
      >
        {children}
      </div>

      {pending && (
        <div className="pointer-events-none absolute inset-x-0 top-24 flex justify-center">
          <span
            role="status"
            // One line at every width: the sentence is 31 characters, which
            // fits a 375px screen's 343px of content with room to spare, and
            // a pill that wrapped to two lines would read as a warning
            // rather than as a wait.
            className="sticky top-1/2 inline-flex max-w-[calc(100%-1rem)] items-center gap-2 whitespace-nowrap rounded-full border bg-card px-5 py-2.5 text-xs font-medium shadow-lg"
          >
            <Loader2 className="size-3.5 animate-spin text-primary" />
            Момент, ги издвојуваме понудите…
          </span>
        </div>
      )}
    </div>
  );
}
