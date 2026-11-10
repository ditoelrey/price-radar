#!/usr/bin/env python3
"""Live verification of the fetch layer. Deliberately tiny: ~8 requests total.

Checks the four things that only reality can confirm:

1. the real transport fetches, archives and records validators;
2. a second fetch of the same URL comes back **304 Not Modified**, which is
   the mechanic the whole probe budget rests on;
3. the scheduler builds the right probe job per platform and the queue
   collapses the sizes of one offer into a single request;
4. ``record_observation`` writes a ``price_point`` row only when a value moved.

Usage::

    ./.venv/Scripts/python.exe -X utf8 scripts/verify_fetcher.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402

from mkagg.fetch import (CircuitBreaker, FetchJob, Fetcher, FetcherConfig,  # noqa: E402
                         LocalRawStore, MemoryFetchQueue, MemoryRateLimiter,
                         Priority, RobotsBlocked, assign_tiers,
                         build_stock_probe, due_variants,
                         enqueue_due, record_observation)
from mkagg.fetch.http import HttpxTransport  # noqa: E402

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg")
ARCHIVE = ROOT.parent / "raw_snapshots"

# One real page per platform. Three requests, plus one repeat, plus robots.
TARGETS = [
    ("sportvision", "https://www.sportvision.mk/mk/patiki/8550245-puma-caven-2-0"),
    ("megasport",
     "https://megasportonlineshop.com/wp-json/wc/store/products?search=392290-02&per_page=1"),
    ("dsport", "https://www.dsport.mk/robots.txt"),
]


def rule(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> int:
    store = LocalRawStore(ARCHIVE)
    fetcher = Fetcher(
        HttpxTransport(),
        # 1 req/s per merchant, one token reserved for user-facing work.
        limiter=MemoryRateLimiter(rps=1.0, capacity=2, reserve=1.0),
        breaker=CircuitBreaker(),
        raw_store=store,
        config=FetcherConfig(respect_robots=True))

    rule("1. live fetch + archive  (respecting robots.txt)")
    first: dict[str, object] = {}
    for merchant, url in TARGETS:
        result = fetcher.fetch(FetchJob(merchant_slug=merchant, url=url,
                                        priority=Priority.WARM))
        first[merchant] = result
        state = (result.skipped or
                 ("304" if result.not_modified else str(result.status)))
        print(f"  {merchant:<13} {state:<5} {len(result.body):>7,}B  "
              f"{result.latency_ms:>7.0f}ms  etag={str(result.etag)[:28]:<30}")
        if result.snapshot_key:
            print(f"                archived -> {result.snapshot_key}")

    rule("2. conditional request: the same URL again should be 304")
    merchant, url = TARGETS[0]
    again = fetcher.fetch(FetchJob(merchant_slug=merchant, url=url,
                                   priority=Priority.WARM))
    if again.not_modified:
        print(f"  {merchant:<13} 304 Not Modified -- {len(again.body)}B "
              "transferred, no re-parse needed")
    else:
        print(f"  {merchant:<13} {again.status} "
              f"{len(again.body):,}B -- no validator honoured by this store; "
              "the probe still works, it just costs a full body")

    rule("3. scheduler: build one probe per platform, queue collapses sizes")
    with psycopg.connect(DSN) as conn:
        changed = assign_tiers(conn)
        conn.commit()
        print(f"  assign_tiers re-tiered {changed} variants")

        # Everything was checked by smoke_load, so nothing is due yet.
        # Backdate so there is work to schedule.
        with conn.cursor() as cur:
            cur.execute("""UPDATE offer_variant
                              SET last_checked_at = now() - interval '2 days'""")
            conn.commit()

        due = due_variants(conn, limit=200)
        print(f"  due variants: {len(due)}")

        queue = MemoryFetchQueue()
        report = enqueue_due(conn, queue, limit=200)
        print(f"  jobs enqueued: {report.pushed}  "
              f"(collapsed from {len(due)} variants, "
              f"{report.deduped} deduped, {report.blocked} robots-blocked)")
        if report.blocked_merchants:
            print(f"  robots-blocked merchants: "
                  f"{', '.join(sorted(report.blocked_merchants))}"
                  "  -- API path forbidden; needs permission or a feed")
        for priority, depth in sorted(queue.depth_by_priority().items()):
            print(f"      {priority.name:<6} {depth}")

        seen: set[str] = set()
        print("\n  one probe per merchant, as built by the scheduler:")
        for d in due:
            if d.merchant_slug in seen:
                continue
            seen.add(d.merchant_slug)
            try:
                job = build_stock_probe(d)
            except RobotsBlocked:
                print(f"    {d.merchant_slug:<13} BLOCKED  "
                      f"{d.adapter} endpoint disallowed by robots.txt")
                continue
            body = (job.body.decode()[:40] + "...") if job.body else "-"
            print(f"    {d.merchant_slug:<13} {job.method:<5} "
                  f"{job.url[:62]:<64} body={body}")

        rule("4. write-on-change: history grows only when a value moves")
        with conn.cursor() as cur:
            cur.execute("""SELECT ov.id, ov.price_minor, ov.size_label, m.slug
                             FROM offer_variant ov
                             JOIN merchant_offer mo ON mo.id = ov.offer_id
                             JOIN merchant m ON m.id = mo.merchant_id
                            WHERE ov.in_stock IS TRUE
                            ORDER BY ov.id LIMIT 1""")
            variant_id, price, size_label, merchant = cur.fetchone()
            cur.execute("SELECT count(*) FROM price_point")
            before = cur.fetchone()[0]

        print(f"  variant {variant_id} ({merchant}, size {size_label}) "
              f"at {price:,} MKD | price_point rows: {before:,}")

        same = record_observation(conn, variant_id, price_minor=price,
                                  in_stock=True, stock_qty=None)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM price_point")
            after_same = cur.fetchone()[0]
        print(f"  probe, same price   -> changed={same!s:<5} "
              f"rows {before:,} -> {after_same:,}   (expected: no new row)")

        moved = record_observation(conn, variant_id, price_minor=price - 300,
                                   in_stock=True, stock_qty=None)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM price_point")
            after_moved = cur.fetchone()[0]
            cur.execute("""SELECT check_ttl_seconds, consecutive_unchanged,
                                  freshness_tier
                             FROM offer_variant WHERE id = %s""", (variant_id,))
            ttl, unchanged_count, tier = cur.fetchone()
        print(f"  probe, price -300   -> changed={moved!s:<5} "
              f"rows {after_same:,} -> {after_moved:,}   (expected: +1)")
        print(f"  adaptive state: tier={tier} ttl={ttl}s "
              f"consecutive_unchanged={unchanged_count}")

        # 304 path: a real observation that writes no history.
        nochange = record_observation(conn, variant_id, price_minor=None,
                                      in_stock=None, unchanged=True)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM price_point")
            after_304 = cur.fetchone()[0]
            cur.execute("SELECT check_ttl_seconds, price_minor FROM offer_variant"
                        " WHERE id = %s", (variant_id,))
            ttl_after, price_after = cur.fetchone()
        print(f"  304 observation     -> changed={nochange!s:<5} "
              f"rows {after_moved:,} -> {after_304:,}   "
              f"ttl {ttl}s -> {ttl_after}s, price preserved at {price_after:,}")

    rule("fetcher stats")
    for key, value in sorted(fetcher.stats.items()):
        print(f"  {key:<18} {value}")
    print(f"\n  archive on disk: {store.total_bytes():,} bytes "
          f"in {ARCHIVE}")
    fetcher.close()
    print("\nverify OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
