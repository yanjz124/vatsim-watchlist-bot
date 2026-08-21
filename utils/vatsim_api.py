# utils/vatsim_api.py
"""
Centralized VATSIM/VATUSA API client with:
- Per-host token-bucket rate limiting (avoids 429s)
- Per-URL TTL caching (avoids duplicate fetches)
- Request coalescing (multiple concurrent calls for the same URL = 1 fetch)
- Stale-on-error fallback (serve last good payload if upstream fails)

All callers should go through this module instead of opening their own
aiohttp sessions to data.vatsim.net / api.vatusa.net / api.vatsim.net.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp


VATSIM_UPSTREAM_INTERVAL = 15.0   # seconds — VATSIM publishes a fresh feed every 15s
DATAFEED_BUFFER = 1.0             # extra delay before re-fetching to let upstream settle
DATAFEED_MIN_TTL = 5.0            # never re-fetch faster than this (clamps stale data)
DATAFEED_MAX_TTL = 30.0           # never cache longer than this (clamps clock skew)


def _parse_update_ts(payload: Optional[dict]) -> Optional[float]:
    """Pull general.update_timestamp out of the datafeed and return its
    POSIX time (seconds since epoch), or None if missing/unparseable."""
    if not isinstance(payload, dict):
        return None
    ts = payload.get("general", {}).get("update_timestamp")
    if not ts:
        return None
    try:
        # ISO 8601, e.g. "2024-01-15T12:30:45.123456Z"
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).astimezone(timezone.utc).timestamp()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

class _RequestCoalescer:
    """Collapse N concurrent calls for the same key into a single in-flight fetch."""

    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}

    async def get(self, key: str, fetch_fn):
        existing = self._pending.get(key)
        if existing is not None and not existing.done():
            return await existing

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[key] = fut
        try:
            result = await fetch_fn()
            if not fut.done():
                fut.set_result(result)
            return result
        except Exception as e:
            if not fut.done():
                fut.set_exception(e)
            raise
        finally:
            self._pending.pop(key, None)


class _TtlCache:
    def __init__(self):
        self._data: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: float):
        self._data[key] = (value, time.time() + ttl)


class _TokenBucket:
    """Async token bucket. rate=tokens/sec, burst=max tokens."""

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rate
                # Sleep outside lock release? We're inside the lock — that
                # serializes acquires, which is what we want for a per-host bucket.
                await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# Centralized client
# ---------------------------------------------------------------------------

class VatsimAPIs:
    """Singleton client for all VATSIM-family APIs."""

    DATAFEED_URL = "https://data.vatsim.net/v3/vatsim-data.json"

    # TTLs (seconds). Tune as needed.
    DATAFEED_TTL = 14          # datafeed updates every ~15s
    USER_NAME_TTL = 3600       # names rarely change
    USER_PROFILE_TTL = 600     # 10 min — facility/role info can change
    FACILITY_TTL = 600
    ROSTER_TTL = 600
    RATINGS_TTL = 1800         # 30 min
    STATS_TTL = 600
    METAR_TTL = 60

    def __init__(self):
        self._datafeed: Optional[dict] = None
        self._datafeed_expires: float = 0.0
        self._datafeed_lock = asyncio.Lock()

        self._cache = _TtlCache()
        self._coalescer = _RequestCoalescer()
        self._session: Optional[aiohttp.ClientSession] = None

        # Conservative per-host limits. VATUSA in particular is rate-limited.
        self._buckets: dict[str, _TokenBucket] = {
            "api.vatusa.net": _TokenBucket(rate=2.0, burst=5),
            "api.vatsim.net": _TokenBucket(rate=2.0, burst=5),
            "metar.vatsim.net": _TokenBucket(rate=2.0, burst=5),
            "data.vatsim.net": _TokenBucket(rate=2.0, burst=3),
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # -----------------------------------------------------------------
    # Datafeed (special: shared in-memory snapshot, not URL-keyed cache)
    # -----------------------------------------------------------------

    async def get_datafeed(self) -> Optional[dict]:
        """Return the shared VATSIM datafeed snapshot.

        Cache expiration is aligned to the upstream `general.update_timestamp`:
        the cache is held until the next expected upstream refresh
        (update_timestamp + 15s + small buffer), so all loops fired before
        that share a single fetch and the first loop fired after it triggers
        a fresh fetch right when new data becomes available."""
        now = time.time()
        if self._datafeed is not None and now < self._datafeed_expires:
            return self._datafeed

        async with self._datafeed_lock:
            now = time.time()
            if self._datafeed is not None and now < self._datafeed_expires:
                return self._datafeed

            try:
                bucket = self._buckets.get("data.vatsim.net")
                if bucket:
                    await bucket.acquire()
                session = await self._get_session()
                timeout = aiohttp.ClientTimeout(total=15)
                async with session.get(self.DATAFEED_URL, timeout=timeout) as resp:
                    if resp.status == 429:
                        print("[VATSIM API] Datafeed rate limited (429), serving stale.")
                        return self._datafeed
                    if resp.status != 200:
                        print(f"[VATSIM API] Datafeed HTTP {resp.status}, serving stale.")
                        return self._datafeed
                    self._datafeed = await resp.json()

                    # Align cache expiry to upstream's actual refresh schedule.
                    upstream_ts = _parse_update_ts(self._datafeed)
                    if upstream_ts is not None:
                        next_refresh = upstream_ts + VATSIM_UPSTREAM_INTERVAL + DATAFEED_BUFFER
                    else:
                        next_refresh = now + self.DATAFEED_TTL  # fallback
                    self._datafeed_expires = max(
                        next_refresh,
                        now + DATAFEED_MIN_TTL,
                    )
                    self._datafeed_expires = min(
                        self._datafeed_expires,
                        now + DATAFEED_MAX_TTL,
                    )
                    return self._datafeed
            except Exception as e:
                print(f"[VATSIM API] Datafeed fetch error: {e}, serving stale.")
                return self._datafeed

    # -----------------------------------------------------------------
    # Generic rate-limited, cached, coalesced GET
    # -----------------------------------------------------------------

    async def _request(
        self,
        host: str,
        url: str,
        ttl: float,
        as_text: bool = False,
        timeout_s: float = 10.0,
        params: Optional[dict] = None,
    ) -> Optional[Any]:
        cache_key = url if not params else f"{url}?{tuple(sorted(params.items()))}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        async def _fetch():
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

            bucket = self._buckets.get(host)
            if bucket:
                await bucket.acquire()

            session = await self._get_session()
            try:
                timeout = aiohttp.ClientTimeout(total=timeout_s)
                async with session.get(url, params=params, timeout=timeout) as resp:
                    if resp.status == 429:
                        print(f"[VATSIM API] {host} 429 — backing off 30s")
                        await asyncio.sleep(30)
                        return None
                    if resp.status != 200:
                        return None
                    result = await (resp.text() if as_text else resp.json())
                    self._cache.set(cache_key, result, ttl)
                    return result
            except Exception as e:
                print(f"[VATSIM API] {host} GET {url} error: {e}")
                return None

        return await self._coalescer.get(cache_key, _fetch)

    # -----------------------------------------------------------------
    # VATUSA
    # -----------------------------------------------------------------

    async def get_user(self, cid) -> Optional[dict]:
        """Full VATUSA user object. Cached USER_PROFILE_TTL."""
        if cid in ("N/A", 0, None):
            return None
        url = f"https://api.vatusa.net/v2/user/{cid}"
        return await self._request("api.vatusa.net", url, self.USER_PROFILE_TTL)

    async def get_user_name(self, cid) -> str:
        """Full name 'fname lname' from VATUSA, or 'N/A'. Cached USER_NAME_TTL."""
        if cid in ("N/A", 0, None):
            return "N/A"
        url = f"https://api.vatusa.net/v2/user/{cid}"
        data = await self._request("api.vatusa.net", url, self.USER_NAME_TTL)
        if not data:
            return "N/A"
        ud = data.get("data", {}) or {}
        name = f"{ud.get('fname', '')} {ud.get('lname', '')}".strip()
        return name or "N/A"

    async def get_user_full(self, cid, api_key: Optional[str] = None) -> Optional[dict]:
        """VATUSA v1 user endpoint (returns roles, visits, promotions, etc.)
        Pass an apikey for authenticated fields."""
        if cid in ("N/A", 0, None):
            return None
        url = f"https://api.vatusa.net/user/{cid}"
        params = {"apikey": api_key} if api_key else None
        return await self._request("api.vatusa.net", url, self.USER_PROFILE_TTL, params=params)

    async def search_lname(self, lastname: str) -> Optional[dict]:
        """VATUSA last-name search."""
        url = f"https://api.vatusa.net/v2/user/filterlname/{lastname}"
        return await self._request("api.vatusa.net", url, self.USER_PROFILE_TTL)

    async def list_facilities(self) -> Optional[dict]:
        """VATUSA facility list."""
        url = "https://api.vatusa.net/v2/facility/"
        return await self._request("api.vatusa.net", url, self.FACILITY_TTL)

    async def get_facility(self, fac_id) -> Optional[dict]:
        url = f"https://api.vatusa.net/v2/facility/{fac_id}"
        return await self._request("api.vatusa.net", url, self.FACILITY_TTL)

    async def get_facility_roster(self, fac_id, roster_type: str = "both") -> Optional[dict]:
        url = f"https://api.vatusa.net/v2/facility/{fac_id}/roster/{roster_type}"
        return await self._request("api.vatusa.net", url, self.ROSTER_TTL)

    # -----------------------------------------------------------------
    # api.vatsim.net (ratings/stats)
    # -----------------------------------------------------------------

    async def get_ratings(self, cid) -> Optional[dict]:
        if cid in ("N/A", 0, None):
            return None
        url = f"https://api.vatsim.net/api/ratings/{cid}/"
        return await self._request("api.vatsim.net", url, self.RATINGS_TTL)

    async def get_member_stats(self, cid) -> Optional[dict]:
        if cid in ("N/A", 0, None):
            return None
        url = f"https://api.vatsim.net/v2/members/{cid}/stats"
        return await self._request("api.vatsim.net", url, self.STATS_TTL)

    # -----------------------------------------------------------------
    # METAR
    # -----------------------------------------------------------------

    async def get_metar(self, icao: str) -> Optional[str]:
        url = f"https://metar.vatsim.net/{icao.upper()}"
        return await self._request("metar.vatsim.net", url, self.METAR_TTL, as_text=True)

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


# Module-level singleton
vatsim_apis = VatsimAPIs()
