"""Self-hosted product images.

Hotlinking was acceptable for a demo catalogue. At sweep scale it spends six
shops' bandwidth on every page view, and one referer rule at any of them
blanks that shop's photos with no error on our side.

So images are fetched once, through the same :class:`~mkagg.fetch.http.Fetcher`
as everything else -- an image request is still a request to a merchant, and
it belongs under the same rate limiter, robots check and circuit breaker.

Storage is content-addressed by SHA-256 of the bytes:

* **Deduplication**, and not theoretically: the shops publish the same
  manufacturer press photo, so one file backs several products.
* **Immutability**, so the served path can be cached hard and forever.
* **Idempotence**, since re-fetching an unchanged image lands on the row that
  already exists.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .fetch.http import fetch_patiently
from .fetch.queue import FetchJob
from .fetch.ratelimit import BreakerWait, Priority

#: Content types we will store. Anything else is a shop serving us an error
#: page, a tracking pixel or an HTML redirect with a 200.
ALLOWED_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/avif": "avif",
    "image/gif": "gif",
}

#: Skips that are facts about us, not about the image URL.
#:
#: Everything else this loop refuses -- a 404, an HTML error page served as a
#: JPEG, a disallowed path -- is evidence about the URL, and stamping
#: `image_checked_at` is how that evidence stops us re-requesting it on every
#: pass. An open circuit or a spent rate budget is not evidence about
#: anything except our own state, so stamping it would spend the product's
#: 24-hour retry window on our outage and the next pass would skip the
#: product believing it had been checked. Found before it cost us a day: a
#: 20-second drop mid-pass would have stamped thousands of products.
OUR_FAULT_SKIPS = frozenset({"circuit_open", "rate_limited"})

#: Below this a "photo" is a spacer, a tracking pixel or an error page.
MIN_BYTES = 1_024
#: Above this something is wrong; product shots are not 8 MB.
MAX_BYTES = 8 * 1024 * 1024


class ImageStore:
    """Content-addressed files under one root, served as static media."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def relative_path(sha256: str, extension: str) -> str:
        # Two levels of fan-out: a flat directory of 50k files is slow to
        # list and unpleasant on some filesystems.
        return f"{sha256[:2]}/{sha256[2:4]}/{sha256}.{extension}"

    def put(self, data: bytes, content_type: str) -> tuple[str, str, str]:
        """Store bytes, returning ``(sha256, relative_path, extension)``.

        Writing is idempotent: identical bytes resolve to the same path and
        the existing file is left alone.
        """
        extension = ALLOWED_TYPES[normalise_type(content_type)]
        digest = hashlib.sha256(data).hexdigest()
        relative = self.relative_path(digest, extension)
        target = self.root / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temporary name and move, so a crash mid-write cannot
            # leave a truncated file at a path we will treat as complete.
            temporary = target.with_suffix(target.suffix + ".part")
            temporary.write_bytes(data)
            temporary.replace(target)
        return digest, relative, extension

    def exists(self, relative_path: str) -> bool:
        return (self.root / relative_path).exists()

    def total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())


def normalise_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def is_storable(content_type: str | None, data: bytes) -> tuple[bool, str]:
    """Whether a response is actually a usable product photo."""
    normalised = normalise_type(content_type)
    if normalised not in ALLOWED_TYPES:
        return False, f"content_type:{normalised or 'none'}"
    if len(data) < MIN_BYTES:
        return False, f"too_small:{len(data)}"
    if len(data) > MAX_BYTES:
        return False, f"too_large:{len(data)}"
    # Trust the bytes over the header: a shop serving an HTML error page with
    # an image content type is a real thing, and it would otherwise be stored
    # and shown as a broken picture.
    if not _has_image_magic(data):
        return False, "not_an_image"
    return True, ""


def _has_image_magic(data: bytes) -> bool:
    return (
        data[:3] == b"\xff\xd8\xff"                       # jpeg
        or data[:8] == b"\x89PNG\r\n\x1a\n"               # png
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        or data[:6] in (b"GIF87a", b"GIF89a")
        or data[4:12] in (b"ftypavif", b"ftypavis")       # avif
    )


# -----------------------------------------------------------------------------
# The pipeline
# -----------------------------------------------------------------------------

@dataclass
class ImageReport:
    considered: int = 0
    stored: int = 0
    deduplicated: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    bytes_written: int = 0
    breaker_waits: int = 0
    breaker_wait_s: float = 0.0

    def note(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def summary(self) -> str:
        bits = [f"considered={self.considered}", f"stored={self.stored}",
                f"deduped={self.deduplicated}", f"errors={self.errors}",
                f"{self.bytes_written / 1024:.0f}KB"]
        if self.skipped:
            bits.append("skipped=" + ",".join(
                f"{k}:{v}" for k, v in sorted(self.skipped.items())))
        if self.breaker_waits:
            bits.append(f"breaker_waits={self.breaker_waits}"
                        f"({self.breaker_wait_s:.0f}s)")
        return "  ".join(bits)


PENDING_SQL = """
SELECT p.id, p.image_url, m.slug AS merchant_slug
  FROM product p
  LEFT JOIN LATERAL (
      SELECT m2.slug
        FROM merchant_offer mo
        JOIN merchant m2 ON m2.id = mo.merchant_id
       WHERE mo.product_id = p.id AND mo.status = 'active'
       ORDER BY mo.id
       LIMIT 1
  ) m ON true
 WHERE p.image_asset_id IS NULL
   AND p.image_url IS NOT NULL
   AND (p.image_checked_at IS NULL
        OR p.image_checked_at < now() - make_interval(hours => %(retry_hours)s))
 ORDER BY p.image_checked_at NULLS FIRST, p.id
 LIMIT %(limit)s
"""


def fetch_product_images(conn, fetcher, store: ImageStore, *,
                         limit: int = 200, retry_hours: int = 24,
                         priority: Priority = Priority.COLD,
                         breaker_wait: BreakerWait | None = None
                         ) -> ImageReport:
    """Download and store photos for products that do not have one yet.

    Runs at ``COLD`` priority: an image is the most preemptible request in
    the system, and must never compete with a click-time verification.

    ``image_checked_at`` is stamped even on failure, so a dead URL is retried
    on a schedule rather than on every pass -- otherwise a handful of broken
    links would be re-requested forever.
    """
    report = ImageReport()
    waiter = BreakerWait() if breaker_wait is None else breaker_wait

    with conn.cursor() as cur:
        cur.execute(PENDING_SQL, {"limit": limit, "retry_hours": retry_hours})
        pending = cur.fetchall()

    for product_id, image_url, merchant_slug in pending:
        report.considered += 1
        result = fetch_patiently(fetcher, FetchJob(
            merchant_slug=merchant_slug or "unknown",
            url=image_url, kind="image", priority=priority), waiter)

        if result.skipped:
            report.note(result.skipped)
            # See OUR_FAULT_SKIPS: our own outage must not consume this
            # product's 24-hour retry window.
            if result.skipped not in OUR_FAULT_SKIPS:
                _stamp(conn, product_id)
            continue
        if not result.ok:
            report.errors += 1
            report.note(f"http_{result.status}")
            _stamp(conn, product_id)
            continue

        ok, reason = is_storable(result.content_type, result.body)
        if not ok:
            report.note(reason)
            _stamp(conn, product_id)
            continue

        try:
            digest, relative, _ext = store.put(result.body, result.content_type)
        except (OSError, KeyError) as exc:
            report.errors += 1
            report.note(f"store_failed:{type(exc).__name__}")
            _stamp(conn, product_id)
            continue

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO image_asset (sha256, path, content_type, bytes,
                                            source_url)
                        VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (sha256) DO UPDATE SET path = image_asset.path
                     RETURNING id, (xmax = 0) AS inserted""",
                (digest, relative, normalise_type(result.content_type),
                 len(result.body), image_url))
            asset_id, inserted = cur.fetchone()
            cur.execute(
                """UPDATE product
                      SET image_asset_id = %s, image_checked_at = now(),
                          updated_at = now()
                    WHERE id = %s""",
                (asset_id, product_id))
        conn.commit()

        if inserted:
            report.stored += 1
            report.bytes_written += len(result.body)
        else:
            # The same press photo already stored under another product.
            report.deduplicated += 1

    report.breaker_waits = waiter.waits
    report.breaker_wait_s = waiter.spent_s
    return report


def _stamp(conn, product_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE product SET image_checked_at = now() WHERE id = %s",
                    (product_id,))
    conn.commit()


_SAFE_PATH = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}\.[a-z]{3,4}$")


def is_safe_media_path(path: str) -> bool:
    """Guard for anything that resolves a stored path back to a file."""
    return bool(_SAFE_PATH.match(path or ""))
