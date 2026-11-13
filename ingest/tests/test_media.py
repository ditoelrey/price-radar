"""Image pipeline tests.

What matters here is what we refuse to store. A shop serving an HTML error
page with `Content-Type: image/jpeg` is a real thing, and storing it would
put a broken picture on a product card with nothing in the logs.
"""
from __future__ import annotations

import pytest

from mkagg.fetch import (BreakerWait, CircuitBreaker, FetchJob, Fetcher,
                         FetcherConfig, MemoryRateLimiter, StubTransport)
from mkagg.media import (ALLOWED_TYPES, MAX_BYTES, MIN_BYTES, OUR_FAULT_SKIPS,
                         ImageStore, fetch_product_images, is_safe_media_path,
                         is_storable, normalise_type)

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 4000
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4000
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 4000
GIF = b"GIF89a" + b"\x00" * 4000


class TestImageStore:
    def test_round_trip(self, tmp_path):
        store = ImageStore(tmp_path)
        digest, path, ext = store.put(JPEG, "image/jpeg")

        assert len(digest) == 64
        assert ext == "jpg"
        assert path == f"{digest[:2]}/{digest[2:4]}/{digest}.jpg"
        assert store.exists(path)
        assert (tmp_path / path).read_bytes() == JPEG

    def test_identical_bytes_deduplicate(self, tmp_path):
        """Not theoretical: the shops publish the same press photo.

        Content addressing means one file backs several products, which is
        the main reason to key on the bytes rather than the URL.
        """
        store = ImageStore(tmp_path)
        first = store.put(JPEG, "image/jpeg")
        second = store.put(JPEG, "image/jpeg")

        assert first == second
        assert len(list(tmp_path.rglob("*.jpg"))) == 1

    def test_different_bytes_do_not_collide(self, tmp_path):
        store = ImageStore(tmp_path)
        a, _, _ = store.put(JPEG, "image/jpeg")
        b, _, _ = store.put(JPEG + b"different", "image/jpeg")
        assert a != b

    def test_no_partial_files_left_behind(self, tmp_path):
        """Writes go to a .part name and are moved into place."""
        store = ImageStore(tmp_path)
        store.put(PNG, "image/png")
        assert list(tmp_path.rglob("*.part")) == []

    def test_content_type_decides_the_extension(self, tmp_path):
        store = ImageStore(tmp_path)
        assert store.put(PNG, "image/png")[2] == "png"
        assert store.put(WEBP, "image/webp; charset=binary")[2] == "webp"

    def test_unknown_type_is_refused(self, tmp_path):
        store = ImageStore(tmp_path)
        with pytest.raises(KeyError):
            store.put(b"<html>", "text/html")


class TestStorableGuard:
    @pytest.mark.parametrize("data,content_type", [
        (JPEG, "image/jpeg"), (PNG, "image/png"),
        (WEBP, "image/webp"), (GIF, "image/gif"),
    ])
    def test_real_images_pass(self, data, content_type):
        ok, reason = is_storable(content_type, data)
        assert ok, reason

    def test_html_with_an_image_content_type_is_refused(self):
        """The failure this guard exists for.

        A shop returning its error page with `Content-Type: image/jpeg` and a
        200 would otherwise be stored and rendered as a broken photo, with
        nothing anywhere saying why.
        """
        html = b"<!DOCTYPE html><html><body>Not found</body></html>" + b" " * 4000
        ok, reason = is_storable("image/jpeg", html)
        assert not ok
        assert reason == "not_an_image"

    def test_tracking_pixels_and_spacers_are_refused(self):
        ok, reason = is_storable("image/gif", b"GIF89a" + b"\x00" * 20)
        assert not ok
        assert reason.startswith("too_small")

    def test_absurdly_large_is_refused(self):
        ok, reason = is_storable("image/jpeg", JPEG + b"\x00" * MAX_BYTES)
        assert not ok
        assert reason.startswith("too_large")

    def test_non_image_content_type_is_refused(self):
        for content_type in ("text/html", "application/json", None, ""):
            ok, reason = is_storable(content_type, JPEG)
            assert not ok
            assert reason.startswith("content_type")

    def test_thresholds_are_sane(self):
        assert MIN_BYTES >= 512
        assert MAX_BYTES <= 32 * 1024 * 1024
        assert "image/jpeg" in ALLOWED_TYPES and "image/webp" in ALLOWED_TYPES

    def test_normalise_type_strips_parameters(self):
        assert normalise_type("image/JPEG; charset=binary") == "image/jpeg"
        assert normalise_type(None) == ""


class TestSafeMediaPath:
    def test_accepts_what_the_store_produces(self, tmp_path):
        _, path, _ = ImageStore(tmp_path).put(JPEG, "image/jpeg")
        assert is_safe_media_path(path)

    @pytest.mark.parametrize("path", [
        "../../etc/passwd",
        "ab/cd/../../../secret.jpg",
        "/absolute/path.jpg",
        "ab/cd/not-a-hash.jpg",
        "", None,
    ])
    def test_rejects_anything_else(self, path):
        assert not is_safe_media_path(path)

# ---------------------------------------------------------------------------
# The 24-hour retry window
# ---------------------------------------------------------------------------

class RecordingCursor:
    def __init__(self, conn):
        self.conn = conn
        self._out = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, query, params=None):
        self.conn.queries.append((query, params))
        if "FROM product p" in query:
            self._out = list(self.conn.pending)
        elif "INSERT INTO image_asset" in query:
            self._out = [(1, True)]
        else:
            self._out = []

    def fetchall(self):
        return self._out

    def fetchone(self):
        return self._out[0] if self._out else None


class RecordingConn:
    """Enough connection to see which UPDATEs the image pass issues."""

    def __init__(self, pending):
        self.pending = pending
        self.queries = []

    def cursor(self):
        return RecordingCursor(self)

    def commit(self):
        pass

    def stamped(self):
        # The UPDATE only. The selection query names image_checked_at too,
        # in its WHERE clause, and matching that made every one of these
        # tests pass or fail for the wrong reason.
        return [q for q, _ in self.queries if "image_checked_at = now()" in q]


class ManualClock:
    def __init__(self, start=1000.0):
        self.now = start
        self.slept = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept += seconds
        self.now += seconds


PENDING = [(7, "https://www.sportvision.mk/img/a.jpg", "sportvision")]
JPEG_CT = {"content-type": "image/jpeg"}


def image_fetcher(routes, *, clock=None, limiter=None):
    extra = {"clock": clock, "sleep": clock.sleep} if clock else {}
    return Fetcher(
        StubTransport(routes=routes),
        limiter=limiter or MemoryRateLimiter(rps=1000, capacity=1000, reserve=0),
        breaker=CircuitBreaker(clock=clock) if clock else CircuitBreaker(),
        config=FetcherConfig(respect_robots=False, max_attempts=1), **extra)


def trip(fetcher, path="/img/fail"):
    """Five failures: the breaker opens on this domain."""
    for i in range(5):
        fetcher.fetch(FetchJob(
            merchant_slug="sportvision",
            url=f"https://www.sportvision.mk{path}/{i}"))


class TestRetryWindow:
    """What may and may not spend a product's 24-hour retry window.

    `image_checked_at` exists so a dead URL is retried on a schedule rather
    than on every pass. The selection query then ignores that product for a
    day, which makes the stamp the most expensive write in this module: it
    must only ever record evidence about the URL itself.
    """

    def test_an_open_circuit_does_not_stamp_the_product(self, tmp_path):
        """The failure that would have cost a day.

        Every `circuit_open` skip used to stamp. A 20-second drop ten minutes
        into the sweep would have marked the remaining thousands of products
        as checked, and no amount of re-running would have looked at them
        again before tomorrow.
        """
        fetcher = image_fetcher({"/img/fail": (503, {}, b"busy"),
                                 "/img/a.jpg": (200, JPEG_CT, JPEG)})
        trip(fetcher)
        conn = RecordingConn(PENDING)

        report = fetch_product_images(conn, fetcher, ImageStore(tmp_path),
                                      breaker_wait=BreakerWait(max_total_s=0))

        assert report.skipped["circuit_open"] == 1
        assert report.stored == 0
        assert conn.stamped() == []

    def test_a_spent_rate_budget_does_not_stamp_either(self, tmp_path):
        fetcher = image_fetcher(
            {"/img/": (200, JPEG_CT, JPEG)},
            limiter=MemoryRateLimiter(rps=1, capacity=1, reserve=1))
        conn = RecordingConn(PENDING)

        report = fetch_product_images(conn, fetcher, ImageStore(tmp_path))

        assert report.skipped["rate_limited"] == 1
        assert conn.stamped() == []

    def test_a_dead_url_still_stamps(self, tmp_path):
        """The other half of the contract: a 404 IS evidence about the URL."""
        fetcher = image_fetcher({"/img/": (404, {}, b"gone")})
        conn = RecordingConn(PENDING)

        report = fetch_product_images(conn, fetcher, ImageStore(tmp_path))

        assert report.errors == 1
        assert len(conn.stamped()) == 1

    def test_an_html_error_page_still_stamps(self, tmp_path):
        fetcher = image_fetcher(
            {"/img/": (200, JPEG_CT, b"<!DOCTYPE html>" + b" " * 4000)})
        conn = RecordingConn(PENDING)

        report = fetch_product_images(conn, fetcher, ImageStore(tmp_path))

        assert report.skipped["not_an_image"] == 1
        assert len(conn.stamped()) == 1

    def test_waiting_out_a_cooldown_gets_the_image(self, tmp_path):
        clock = ManualClock()
        fetcher = image_fetcher({"/img/fail": (503, {}, b"busy"),
                                 "/img/a.jpg": (200, JPEG_CT, JPEG)},
                                clock=clock)
        trip(fetcher)
        conn = RecordingConn(PENDING)

        report = fetch_product_images(conn, fetcher, ImageStore(tmp_path),
                                      breaker_wait=BreakerWait(sleep=clock.sleep))

        assert report.stored == 1
        assert report.breaker_waits == 1
        assert clock.slept >= 30
        # Stamped by the success path, with an asset to show for it.
        assert len(conn.stamped()) == 1

    def test_our_faults_are_named_and_nothing_else_is(self):
        assert OUR_FAULT_SKIPS == {"circuit_open", "rate_limited"}
        assert "robots_disallowed" not in OUR_FAULT_SKIPS
