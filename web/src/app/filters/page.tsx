/**
 * A deliberately plain page for exercising the category and gender filters.
 *
 * This is a test harness, not a design. It exists because the filters are new
 * all the way down -- V17's taxonomy, the facet walk that fills it, the
 * derivation that resolves it, and two new API parameters -- and the quickest
 * way to see whether that chain is honest is a page that shows every bucket's
 * count next to the rows it returns. The real filter UI is a separate
 * conversation.
 *
 * Two things it is built to make visible, because they are the ones that can
 * quietly be wrong:
 *
 * 1. Each row prints the category and gender the API returned, so a count
 *    that looks plausible can still be checked against what is in it. Asking
 *    for Копачки must return cleats and nothing else.
 * 2. Unknowns are shown rather than hidden. A filter that silently drops the
 *    products it has no label for looks like a working filter over a smaller
 *    shop, which is the failure mode worth catching early.
 *
 * Labels are Macedonian, slugs are English: the URL carries `cleats`, the
 * button says Копачки.
 */
import Link from "next/link";

import { searchProducts, type ProductCard } from "@/lib/api";
import { formatMoney } from "@/lib/format";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** English slug, Macedonian label -- the convention, in one place. */
const CATEGORIES: ReadonlyArray<{ slug?: string; label: string; note?: string }> = [
  { slug: undefined, label: "Сите обувки" },
  { slug: "sneakers", label: "Патики" },
  { slug: "cleats", label: "Копачки" },
  { slug: "shoes_boots", label: "Кондури и чизми" },
  { slug: "slides_sandals", label: "Папучи и сандали" },
  {
    slug: "footwear",
    label: "Неодредени",
    note: "обувки без утврдена подкатегорија",
  },
];

const GENDERS: ReadonlyArray<{ slug?: string; label: string }> = [
  { slug: undefined, label: "Сите" },
  { slug: "men", label: "Мажи" },
  { slug: "women", label: "Жени" },
  { slug: "kids", label: "Деца" },
  { slug: "unisex", label: "Унисекс" },
];

function one(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.length > 0 ? v : undefined;
}

function href(category?: string, gender?: string) {
  const sp = new URLSearchParams();
  if (category) sp.set("category", category);
  if (gender) sp.set("gender", gender);
  const qs = sp.toString();
  return `/filters${qs ? `?${qs}` : ""}`;
}

function Pill({
  active,
  children,
  to,
}: {
  active: boolean;
  children: React.ReactNode;
  to: string;
}) {
  return (
    <Link
      href={to}
      className={[
        "rounded-md border px-3 py-1.5 text-sm transition-colors",
        active
          ? "border-neutral-900 bg-neutral-900 text-white"
          : "border-neutral-300 bg-white text-neutral-700 hover:border-neutral-500",
      ].join(" ")}
    >
      {children}
    </Link>
  );
}

function Row({ item }: { item: ProductCard }) {
  return (
    <tr className="border-b border-neutral-200 align-top">
      <td className="py-2 pr-3">
        <Link
          href={`/products/${item.slug}`}
          className="font-medium underline-offset-2 hover:underline"
        >
          {item.name}
        </Link>
        <div className="text-xs text-neutral-500">{item.brand}</div>
      </td>
      <td className="py-2 pr-3 text-sm">
        {item.categoryMk ?? (
          <span className="text-amber-700">без категорија</span>
        )}
        <div className="font-mono text-[11px] text-neutral-400">
          {item.category ?? "null"}
        </div>
      </td>
      <td className="py-2 pr-3 text-sm">
        {item.gender ?? <span className="text-amber-700">непознат</span>}
      </td>
      <td className="py-2 pr-3 text-right text-sm tabular-nums">
        {item.fromPrice ? formatMoney(item.fromPrice) : "—"}
      </td>
      <td className="py-2 text-right text-sm tabular-nums text-neutral-500">
        {item.merchantCount}
      </td>
    </tr>
  );
}

export default async function FiltersTestPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const category = one(params.category);
  const gender = one(params.gender);

  // pageSize is the API's maximum. A test page wants as much of the bucket as
  // one request gives, so a mislabelled row has somewhere to show up.
  const result = await searchProducts({ category, gender, pageSize: 60 });

  const shown = result.items.length;
  const missingCategory = result.items.filter((i) => !i.category).length;
  const missingGender = result.items.filter((i) => !i.gender).length;

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-xl font-semibold">Тест на филтри</h1>
        <p className="mt-1 text-sm text-neutral-600">
          Категорија и пол, онака како што ги враќа API-то. Привремена
          страница за проверка.
        </p>
      </header>

      <section className="mb-4">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Категорија
        </h2>
        <div className="flex flex-wrap gap-2">
          {CATEGORIES.map((c) => (
            <Pill
              key={c.label}
              active={category === c.slug}
              to={href(c.slug, gender)}
            >
              {c.label}
              {c.note ? (
                <span className="ml-1 text-[11px] opacity-70">({c.note})</span>
              ) : null}
            </Pill>
          ))}
        </div>
      </section>

      <section className="mb-6">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Пол
        </h2>
        <div className="flex flex-wrap gap-2">
          {GENDERS.map((g) => (
            <Pill
              key={g.label}
              active={gender === g.slug}
              to={href(category, g.slug)}
            >
              {g.label}
            </Pill>
          ))}
        </div>
        <p className="mt-2 text-xs text-neutral-500">
          „Мажи“ и „Жени“ ги вклучуваат и унисекс производите, исто како
          филтрите на самите продавници. Производите без утврден пол не се
          прикажуваат во ниту еден филтер по пол.
        </p>
      </section>

      <section className="mb-4 rounded-md border border-neutral-200 bg-neutral-50 p-3 font-mono text-xs text-neutral-700">
        <div>
          GET /api/v1/products?category={category ?? "—"}&amp;gender=
          {gender ?? "—"}&amp;pageSize=60
        </div>
        <div className="mt-1">
          {shown} rows{result.hasMore ? " (има уште)" : ""} · без категорија:{" "}
          {missingCategory} · без пол: {missingGender}
        </div>
      </section>

      {shown === 0 ? (
        <p className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
          Нема производи за овој филтер. Празна страница е точниот одговор ако
          комбинацијата не постои — на пример копачки за жени во продавница
          што не ги продава.
        </p>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-neutral-300 text-left text-xs uppercase tracking-wide text-neutral-500">
              <th className="py-2 pr-3 font-semibold">Производ</th>
              <th className="py-2 pr-3 font-semibold">Категорија</th>
              <th className="py-2 pr-3 font-semibold">Пол</th>
              <th className="py-2 pr-3 text-right font-semibold">Од</th>
              <th className="py-2 text-right font-semibold">Продавници</th>
            </tr>
          </thead>
          <tbody>
            {result.items.map((item) => (
              <Row key={item.slug} item={item} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
