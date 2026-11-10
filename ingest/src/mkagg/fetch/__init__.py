"""Fetch layer: the only part of the pipeline that touches the network.

    discovery/scheduler  ->  FetchQueue  ->  Fetcher  ->  RawStore
                                                      ->  adapter.parse_*  (pure)
                                                      ->  loader           (db)

Priority ladder, highest first -- background work is preemptible by design and
must never be able to starve a user waiting at the redirect:

    CLICK  >  HOVER  >  SWR  >  HOT  >  WARM  >  COLD
"""
from .http import (DEFAULT_USER_AGENT, Fetcher, FetcherConfig, FetchResult,
                   HttpxTransport, MemoryValidatorStore, RobotsCache,
                   StubTransport, Transport)
from .queue import DEDUPE_TTL_S, FetchJob, MemoryFetchQueue, RedisFetchQueue
from .ratelimit import (BUDGET_MS, CircuitBreaker, MemoryRateLimiter, Priority,
                        RedisRateLimiter)
from .rawstore import LocalRawStore, NullRawStore, Snapshot, snapshot_key
from .scheduler import (API_ROUTE_ADAPTERS, HOT_SET_SIZE, TIERS, WARM_SET_SIZE,
                        EnqueueReport, RobotsBlocked, assign_tiers,
                        build_stock_probe, due_variants, enqueue_due,
                        mark_checked, next_ttl, record_observation)

__all__ = [
    "API_ROUTE_ADAPTERS", "BUDGET_MS", "DEDUPE_TTL_S", "DEFAULT_USER_AGENT",
    "EnqueueReport", "HOT_SET_SIZE", "RobotsBlocked", "TIERS",
    "WARM_SET_SIZE", "CircuitBreaker", "FetchJob", "FetchResult", "Fetcher",
    "FetcherConfig", "HttpxTransport", "LocalRawStore", "MemoryFetchQueue",
    "MemoryRateLimiter", "MemoryValidatorStore", "NullRawStore", "Priority",
    "RedisFetchQueue", "RedisRateLimiter", "RobotsCache", "Snapshot",
    "StubTransport", "Transport", "assign_tiers", "build_stock_probe",
    "due_variants", "enqueue_due", "mark_checked", "next_ttl",
    "record_observation", "snapshot_key",
]
