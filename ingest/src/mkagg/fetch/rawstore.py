"""Raw response archive.

Every fetched payload is written here verbatim before anything parses it. This
is cheap (gzipped HTML is ~40 KB; Cloudflare R2 charges nothing for egress)
and it buys three things that are otherwise impossible:

1. **Re-parse history.** When a parser turns out to have been wrong -- and the
   Sport Vision size-boundary bug proves they are -- the fix can be replayed
   over the archive instead of losing the affected days of price history.
2. **Layout-change detection.** Diffing today's payload against last week's
   shows a redesign before the fill-rate alert fires.
3. **Golden fixtures for free.** A regression test is a copy of the archived
   payload that broke.

Local disk is the dev backend. In production this is R2/S3 behind the same
interface; nothing above this module knows the difference.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

_EXT = {
    "application/json": "json",
    "text/html": "html",
    "text/xml": "xml",
    "application/xml": "xml",
    "text/plain": "txt",
}

_SAFE = re.compile(r"[^a-z0-9_.-]+")


def snapshot_key(merchant_slug: str, url: str, content_type: str,
                 fetched_at: datetime | None = None,
                 body: bytes | None = None) -> str:
    """Stable, sortable, collision-resistant archive key.

    ``{merchant}/{YYYY-MM-DD}/{url-hash}-{body-hash}.{ext}.gz``

    Partitioned by merchant and day so a day's crawl can be listed or expired
    as a unit. The URL hash identifies the resource; the short body hash keeps
    two different responses for the same URL on the same day from colliding,
    which is exactly what happens when a price changes mid-day.
    """
    when = (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    body_hash = hashlib.sha256(body or b"").hexdigest()[:8]
    ext = _EXT.get((content_type or "").split(";")[0].strip().lower(), "bin")
    slug = _SAFE.sub("-", merchant_slug.lower())
    return f"{slug}/{when:%Y-%m-%d}/{url_hash}-{body_hash}.{ext}.gz"


@dataclass(slots=True)
class Snapshot:
    key: str
    body: bytes
    meta: dict


class RawStore(Protocol):
    def put(self, merchant_slug: str, url: str, body: bytes,
            content_type: str, **meta) -> str: ...
    def get(self, key: str) -> Snapshot: ...
    def exists(self, key: str) -> bool: ...


class LocalRawStore:
    """Filesystem archive. Gzips on write; sidecar JSON holds the metadata."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Keys are generated internally, but refuse traversal regardless --
        # a key could one day come from a database row.
        if ".." in Path(key).parts or Path(key).is_absolute():
            raise ValueError(f"unsafe snapshot key: {key!r}")
        return self.root / key

    def put(self, merchant_slug: str, url: str, body: bytes,
            content_type: str, **meta) -> str:
        key = snapshot_key(merchant_slug, url, content_type, body=body)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(body, compresslevel=6))
        path.with_suffix(path.suffix + ".meta.json").write_text(
            json.dumps({
                "merchant_slug": merchant_slug,
                "url": url,
                "content_type": content_type,
                "bytes": len(body),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                **meta,
            }, ensure_ascii=False),
            encoding="utf-8")
        return key

    def get(self, key: str) -> Snapshot:
        path = self._path(key)
        meta_path = path.with_suffix(path.suffix + ".meta.json")
        meta = (json.loads(meta_path.read_text(encoding="utf-8"))
                if meta_path.exists() else {})
        return Snapshot(key=key, body=gzip.decompress(path.read_bytes()),
                        meta=meta)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def iter_keys(self, merchant_slug: str | None = None,
                  day: str | None = None):
        """Walk archived keys, newest day first. Used by the re-parse tool."""
        pattern = f"{merchant_slug or '*'}/{day or '*'}/*.gz"
        for path in sorted(self.root.glob(pattern), reverse=True):
            if path.name.endswith(".meta.json"):
                continue
            yield str(path.relative_to(self.root)).replace("\\", "/")

    def total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*.gz"))


class NullRawStore:
    """Discards everything. For tests that are not about archiving."""

    def put(self, merchant_slug: str, url: str, body: bytes,
            content_type: str, **meta) -> str:
        return snapshot_key(merchant_slug, url, content_type, body=body)

    def get(self, key: str) -> Snapshot:
        raise KeyError(key)

    def exists(self, key: str) -> bool:
        return False
