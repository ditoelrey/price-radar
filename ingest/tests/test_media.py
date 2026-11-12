"""Image pipeline tests.

What matters here is what we refuse to store. A shop serving an HTML error
page with `Content-Type: image/jpeg` is a real thing, and storing it would
put a broken picture on a product card with nothing in the logs.
"""
from __future__ import annotations

import pytest

from mkagg.media import (ALLOWED_TYPES, MAX_BYTES, MIN_BYTES, ImageStore,
                         is_safe_media_path, is_storable, normalise_type)

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
