#!/usr/bin/env python3
"""The ingestion entrypoint: discovery, then the worker loop.

    discover -> queue -> Fetcher -> adapter -> loader -> Postgres

Everything goes through the fetcher, so the per-domain rate limiter, the
robots check and the circuit breaker apply to discovery and probing alike.

Examples::

    # enumerate up to 20 products per merchant and ingest them
    python -X utf8 scripts/run_pipeline.py discover --limit 20

    # one merchant only, tiny, for a smoke check
    python -X utf8 scripts/run_pipeline.py discover -m sportvision --limit 3

    # refresh what the scheduler says is due
    python -X utf8 scripts/run_pipeline.py probe

    # keep going (ctrl-c to stop)
    python -X utf8 scripts/run_pipeline.py serve --cycles 10
"""
from __future__ import annotations

import argparse
import functools
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402

from mkagg.discover import discover, product_jobs  # noqa: E402
from mkagg.fetch import (CircuitBreaker, Fetcher, FetcherConfig,  # noqa: E402
                         LocalRawStore, MemoryFetchQueue, MemoryRateLimiter,
                         Priority, assign_tiers, enqueue_due)
from mkagg.fetch.http import DEFAULT_USER_AGENT, HttpxTransport  # noqa: E402
from mkagg.worker import run_forever, run_once  # noqa: E402

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg")
ARCHIVE = Path(os.environ.get("RAW_ARCHIVE", ROOT.parent / "raw_snapshots"))
USER_AGENT = os.environ.get("CRAWLER_USER_AGENT", DEFAULT_USER_AGENT)


def build_fetcher(rps: float) -> Fetcher:
    return Fetcher(
        HttpxTransport(),
        # One shared budget per merchant, with a token held back that only
        # user-facing work (click-time, hover) may spend.
        limiter=MemoryRateLimiter(rps=rps, capacity=max(2.0, rps * 2),
                                  reserve=1.0),
        breaker=CircuitBreaker(),
        raw_store=LocalRawStore(ARCHIVE),
        config=FetcherConfig(user_agent=USER_AGENT, respect_robots=True))


def active_merchants(conn, only: list[str] | None):
    with conn.cursor() as cur:
        cur.execute("""SELECT slug, adapter, base_url, api_requires_permission
                         FROM merchant WHERE is_active ORDER BY slug""")
        rows = cur.fetchall()
    if only:
        rows = [r for r in rows if r[0] in set(only)]
    return rows


def cmd_discover(args) -> int:
    fetcher = build_fetcher(args.rps)
    queue = MemoryFetchQueue()
    with psycopg.connect(DSN) as conn:
        print(f"{'merchant':<14}{'strategy':<12}{'reqs':>6}{'found':>7}"
              f"{'queued':>8}   notes")
        total_found = 0
        for slug, adapter, base_url, _blocked in active_merchants(
                conn, args.merchant):
            report = discover(fetcher, slug, adapter, base_url,
                              limit=args.limit,
                              max_requests=args.max_requests)
            jobs = product_jobs(report, priority=Priority.COLD)
            queued = sum(1 for j in jobs if queue.push(j))
            total_found += report.count
            note = report.notes[0] if report.notes else ""
            print(f"{slug:<14}{report.strategy:<12}{report.requests:>6}"
                  f"{report.count:>7}{queued:>8}   {note[:46]}")
            if report.exhausted_facets:
                print(f"{'':<14}  {report.exhausted_facets} facet(s) did not "
                      "saturate -- unknown tail on this store")

        print(f"\ndiscovered {total_found} product URLs, "
              f"{len(queue)} jobs queued")
        if not len(queue):
            return 0

        print("\ndraining the queue ...")
        report = run_once(conn, fetcher, queue, max_jobs=args.max_jobs)
        print(f"  {report.summary()}")
        for outcome in report.ingests:
            print(f"  {outcome.summary()}")
    fetcher.close()
    return 0


def cmd_probe(args) -> int:
    fetcher = build_fetcher(args.rps)
    queue = MemoryFetchQueue()
    with psycopg.connect(DSN) as conn:
        retiered = assign_tiers(conn)
        conn.commit()
        enq = enqueue_due(conn, queue, limit=args.limit or 500)
        print(f"re-tiered {retiered} variants; queued {enq.pushed} probes "
              f"({enq.deduped} deduped, {enq.blocked} robots-blocked)")
        if enq.blocked_merchants:
            print("  robots-blocked: " + ", ".join(sorted(enq.blocked_merchants)))
        if not len(queue):
            print("nothing due")
            return 0
        report = run_once(conn, fetcher, queue, max_jobs=args.max_jobs)
        print(f"  {report.summary()}")
    fetcher.close()
    return 0


def cmd_serve(args) -> int:
    fetcher = build_fetcher(args.rps)
    queue = MemoryFetchQueue()
    with psycopg.connect(DSN) as conn:
        def refill() -> None:
            assign_tiers(conn)
            conn.commit()
            enqueue_due(conn, queue, limit=args.limit or 500)

        print(f"serving: rps={args.rps}/merchant  cycles={args.cycles}")
        run_forever(conn, fetcher, queue,
                    functools.partial(refill), cycles=args.cycles,
                    idle_sleep_s=args.idle_sleep)
    fetcher.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn in (("discover", cmd_discover), ("probe", cmd_probe),
                     ("serve", cmd_serve)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("-m", "--merchant", action="append",
                       help="restrict to this merchant slug (repeatable)")
        p.add_argument("--limit", type=int, default=None,
                       help="max product URLs per merchant / probes to queue")
        p.add_argument("--max-requests", type=int, default=400,
                       help="hard request ceiling per merchant for discovery")
        p.add_argument("--max-jobs", type=int, default=500,
                       help="max jobs drained in one worker cycle")
        p.add_argument("--rps", type=float, default=1.0,
                       help="requests per second per merchant domain")
        p.add_argument("--cycles", type=int, default=None)
        p.add_argument("--idle-sleep", type=float, default=5.0)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
