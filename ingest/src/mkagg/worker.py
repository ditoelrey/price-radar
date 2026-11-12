"""The worker loop: the piece that joins the fetcher to the loader.

    queue -> Fetcher -> adapter.parse_* -> loader (catalog) / probe (stock)

Two paths, on purpose, because the two kinds of work need different
protection:

``catalog_parse``
    Goes through the full loader -- stage, validate against the merchant's own
    7-day median, promote or reject. A catalogue sweep is exactly where a
    silently broken parser does its damage, so it gets the gate.

``stock_probe``
    Goes straight to ``record_observation``, with a cheap plausibility guard.
    Staging a single-offer price check would cost more than it protects, and
    the aggregate-shape checks the gate performs are meaningless for one row.
    The guard catches the failure that matters here instead: a price that
    moved implausibly far, which is what a half-broken parser produces.

The loop never raises on a merchant's behalf. A store that is down, slow, rude
or newly redesigned costs its own jobs and nothing else.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from .adapters import get_adapter
from .adapters.aspnet_mk import sizes_request
from .fetch.http import FetchResult
from .fetch.queue import FetchJob
from .fetch.ratelimit import Priority
from .fetch.scheduler import mark_checked, record_observation
from .load import ingest
from .models import RawOffer

#: A probe whose price moves further than this is treated as suspect rather
#: than believed. Real sales do not usually halve a price between two checks,
#: but a parser that has started reading the wrong element routinely does.
IMPLAUSIBLE_MOVE = 0.70

#: Adapters that need a second request to assemble a full product record.
#: sport-m and sizeer render an unrendered Razor placeholder where the sizes
#: belong, so the size run only exists behind POST /GetVelicini/.
COMPANION_FETCH_ADAPTERS = frozenset({"aspnet_mk"})


@dataclass
class WorkerReport:
    jobs_processed: int = 0
    fetched: int = 0
    not_modified: int = 0
    skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    http_errors: int = 0
    parse_failures: int = 0
    offers_unpriced: int = 0
    probes_applied: int = 0
    probes_changed: int = 0
    probes_rejected: int = 0
    offers_parsed: int = 0
    ingests: list = field(default_factory=list)
    duration_s: float = 0.0

    def summary(self) -> str:
        bits = [f"jobs={self.jobs_processed}", f"fetched={self.fetched}",
                f"304={self.not_modified}", f"errors={self.http_errors}"]
        if self.skipped:
            bits.append("skipped=" + ",".join(
                f"{k}:{v}" for k, v in sorted(self.skipped.items())))
        if self.probes_applied:
            bits.append(f"probes={self.probes_applied}"
                        f"(changed={self.probes_changed}"
                        f",rejected={self.probes_rejected})")
        if self.offers_parsed:
            bits.append(f"offers={self.offers_parsed}")
        if self.offers_unpriced:
            bits.append(f"unpriced={self.offers_unpriced}")
        bits.append(f"{self.duration_s:.1f}s")
        return "  ".join(bits)


# -----------------------------------------------------------------------------
# Parsing a fetch result
# -----------------------------------------------------------------------------

def _companion_sizes(fetcher, job: FetchJob, merchant_sku: str,
                     base_url: str) -> bytes | None:
    """Fetch the size run for an adapter whose page does not carry it."""
    url, body, headers = sizes_request(base_url, merchant_sku)
    result = fetcher.fetch(FetchJob(
        merchant_slug=job.merchant_slug, url=url, kind=job.kind,
        priority=job.priority, method="POST", body=body, headers=headers))
    return result.body if result.ok else None


def parse_result(fetcher, result: FetchResult, merchant: dict
                 ) -> list[RawOffer]:
    """Turn one successful fetch into offers, using the merchant's adapter."""
    adapter_slug = merchant["adapter"]
    adapter = get_adapter(adapter_slug)
    job = result.job

    if adapter_slug in COMPANION_FETCH_ADAPTERS:
        if job.method == "POST":
            # This *is* the size payload: a stock probe.
            offer = adapter.parse_stock(
                result.body, job.url, job.merchant_slug,
                publishes_stock=merchant["publishes_stock"])
            return [offer] if offer else []
        from .adapters.aspnet_mk import product_id_from_url

        product_id = product_id_from_url(job.url)
        sizes = (_companion_sizes(fetcher, job, product_id, merchant["base_url"])
                 if product_id else None)
        offer = adapter.parse_product(
            result.body, job.url, job.merchant_slug, sizes_payload=sizes,
            publishes_stock=merchant["publishes_stock"])
        return [offer] if offer else []

    # Platforms whose listing endpoints return many records at once.
    if hasattr(adapter, "parse_many") and job.kind != "stock_probe":
        offers = adapter.parse_many(result.body, merchant["base_url"],
                                    job.merchant_slug)
        if offers:
            return offers

    offer = adapter.parse_product(result.body, job.url, job.merchant_slug)
    return [offer] if offer else []


# -----------------------------------------------------------------------------
# Stock probes
# -----------------------------------------------------------------------------

def apply_probe(conn, offer: RawOffer, job: FetchJob,
                report: WorkerReport) -> None:
    """Write a probe outcome, guarding against implausible and absent prices.

    Matching is by the store's own per-size variant id where it exposes one,
    falling back to the size label. One probe answers every size of an offer,
    which is why the queue deduplicates them down to a single request.

    Two things this has to get right, both learned the hard way:

    **Some probe endpoints carry no price at all.** sport-m's and sizeer's
    ``GetVelicini`` returns sizes and stock only, so every variant arrives
    with ``price_minor == 0``. That is *stock-only* information, not a price
    of zero, and it must leave the stored price untouched.

    **Zero is the most dangerous value, so it cannot be tested for
    truthiness.** The first version of the guard read
    ``if old_price and new_price and abs(...)``, which skipped the check
    whenever the new price was 0 -- exactly the case a broken parser
    produces, and exactly the case that would have published "0 MKD".
    """
    # If no size in this payload has a price, the endpoint is stock-only.
    # If *some* do and others do not, that is a parser fault, not a feature.
    payload_has_prices = any(v.price_minor for v in offer.variants)

    with conn.cursor() as cur:
        cur.execute(
            """SELECT ov.id, ov.size_label, ov.merchant_variant_id,
                      ov.price_minor
                 FROM offer_variant ov
                WHERE ov.offer_id = %s""",
            (job.offer_id,))
        rows = cur.fetchall()

    by_variant_id = {r[2]: r for r in rows if r[2]}
    by_label = {r[1]: r for r in rows}

    for variant in offer.variants:
        row = (by_variant_id.get(variant.merchant_variant_id)
               or by_label.get(variant.size_label))
        if row is None:
            # A size the catalogue has not seen. A probe is the wrong place to
            # add rows: let the next catalog_parse introduce it through the
            # gate, where it is counted and validated.
            continue
        variant_id, _label, _vid, old_price = row

        if not payload_has_prices:
            # Stock-only endpoint: keep the stored price, update availability.
            probed_price = old_price
            suspect = False
        else:
            probed_price = variant.price_minor
            # `is None` and `== 0` checked explicitly: never truthiness.
            missing = probed_price is None or probed_price == 0
            moved_too_far = (
                probed_price is not None and old_price
                and abs(probed_price - old_price) / old_price > IMPLAUSIBLE_MOVE)
            suspect = bool(missing or moved_too_far)

        if suspect:
            # Record the disagreement, leave the live value alone. The hot
            # tier will re-check it, and the mismatch shows up in the KPI.
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO verification_event (
                               offer_variant_id, merchant_id, trigger,
                               latency_ms, outcome, shown_price_minor,
                               live_price_minor)
                       SELECT %s, mo.merchant_id, 'shadow', NULL,
                              'price_changed', %s, %s
                         FROM merchant_offer mo WHERE mo.id = %s""",
                    (variant_id, old_price, variant.price_minor, job.offer_id))
            report.probes_rejected += 1
            continue

        changed = record_observation(
            conn, variant_id, price_minor=probed_price,
            in_stock=variant.in_stock, stock_qty=variant.stock_qty)
        report.probes_applied += 1
        report.probes_changed += int(changed)


# -----------------------------------------------------------------------------
# The loop
# -----------------------------------------------------------------------------

def merchants_by_slug(conn) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT slug, id, adapter, base_url, publishes_stock
                         FROM merchant WHERE is_active""")
        return {r[0]: {"slug": r[0], "id": r[1], "adapter": r[2],
                       "base_url": r[3], "publishes_stock": r[4]}
                for r in cur.fetchall()}


def run_once(conn, fetcher, queue, *, max_jobs: int = 500,
             full_sweep: bool = False, ingest_fn=ingest) -> WorkerReport:
    """Drain the queue once: fetch, parse, then apply.

    Catalogue offers are batched per merchant so each merchant's sweep becomes
    one ``ingest_run`` with one gate decision, rather than a run per product.

    ``ingest_fn`` is injectable so the loop's own behaviour -- error
    containment, skip accounting, job budgeting -- can be tested without a
    database, and so a deployment can wrap the loader with its own metrics.
    """
    report = WorkerReport()
    started = time.monotonic()
    merchants = merchants_by_slug(conn)

    catalog: dict[str, list[RawOffer]] = defaultdict(list)
    requests: dict[str, int] = defaultdict(int)
    errors: dict[str, int] = defaultdict(int)
    unanswered: list[int] = []

    while report.jobs_processed < max_jobs:
        job = queue.pop()
        if job is None:
            break
        report.jobs_processed += 1

        merchant = merchants.get(job.merchant_slug)
        if merchant is None:
            # Not our merchant (renamed, deactivated, or a stale queued job).
            continue

        result = fetcher.fetch(job)
        requests[job.merchant_slug] += 1

        if result.skipped:
            report.skipped[result.skipped] += 1
            if job.offer_variant_id:
                unanswered.append(job.offer_variant_id)
            continue

        if result.not_modified:
            report.not_modified += 1
            # Byte-identical: a confirmed no-change, so the TTL still relaxes.
            if job.offer_variant_id:
                record_observation(conn, job.offer_variant_id,
                                   price_minor=None, in_stock=None,
                                   unchanged=True)
            continue

        if not result.ok:
            report.http_errors += 1
            errors[job.merchant_slug] += 1
            if job.offer_variant_id:
                unanswered.append(job.offer_variant_id)
            continue

        report.fetched += 1
        try:
            offers = parse_result(fetcher, result, merchant)
        except Exception:
            # A parser bug must cost this one job, never the whole cycle.
            report.parse_failures += 1
            if job.offer_variant_id:
                unanswered.append(job.offer_variant_id)
            continue

        if not offers:
            report.parse_failures += 1
            if job.offer_variant_id:
                unanswered.append(job.offer_variant_id)
            continue

        # An offer with no price is not an offer: there is nothing to compare,
        # so it cannot appear on a comparison page. Shops do publish these --
        # megasport lists discontinued stock with
        # `data-product_variations="[]"`, `out-of-stock` and a JSON-LD price of
        # 0 -- and letting them through dragged a whole merchant's price fill
        # rate to 80% and had the gate reject the entire run, blocking four
        # perfectly good offers along with the dud.
        #
        # Counted rather than silently dropped: a sudden rise here means a
        # parser stopped finding prices, which is the same symptom with a very
        # different cause.
        # Catalogue offers only. A stock probe is legitimately price-less:
        # sport-m's and sizeer's GetVelicini returns sizes and stock and no
        # price at all, so applying this filter to probes dropped every one of
        # them -- caught immediately by the probe test, which is the whole
        # reason that test asserts a count rather than just "no error".
        if job.kind != "stock_probe":
            priced = [o for o in offers if o.min_price_minor]
            report.offers_unpriced += len(offers) - len(priced)
            offers = priced
            if not offers:
                continue

        # The hint belongs to the job, not the page: it records where
        # discovery found the product, which is the context its title omits.
        if job.category_hint:
            for parsed in offers:
                parsed.category_hint = job.category_hint

        report.offers_parsed += len(offers)

        if job.kind == "stock_probe" and job.offer_id:
            apply_probe(conn, offers[0], job, report)
            conn.commit()
        else:
            catalog[job.merchant_slug].extend(offers)

    # Failed and skipped probes still move last_checked_at forward, so one
    # unreachable merchant cannot monopolise the queue -- but their stored
    # values and TTLs are left alone, because a failure is not evidence about
    # the price.
    if unanswered:
        mark_checked(conn, unanswered)
        conn.commit()

    for slug, offers in catalog.items():
        outcome = ingest_fn(conn, slug, offers, kind="catalog_parse",
                         requests=requests[slug], http_errors=errors[slug],
                         full_sweep=full_sweep)
        report.ingests.append(outcome)

    report.duration_s = time.monotonic() - started
    return report


def run_forever(conn, fetcher, queue, scheduler_refill, *,
                idle_sleep_s: float = 5.0, cycles: int | None = None,
                sleep=time.sleep) -> None:
    """Keep working: refill from the scheduler, drain, repeat.

    ``scheduler_refill`` is a callable that enqueues due work -- normally
    ``functools.partial(enqueue_due, conn, queue)``. Separating it keeps this
    loop testable and lets a deployment choose its own cadence.
    """
    cycle = 0
    while cycles is None or cycle < cycles:
        cycle += 1
        scheduler_refill()
        report = run_once(conn, fetcher, queue)
        if report.jobs_processed == 0:
            sleep(idle_sleep_s)
