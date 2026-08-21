import os
import time
from collections import OrderedDict

import aiohttp

OPENCAGE_KEY = os.getenv("OPENCAGE_KEY")

# Reverse geocoding is called once per position embed, and every monitor
# rebuilds its embed on a fixed refresh interval -- so without a cache the
# request rate scales with (guilds x watched entries online), against a free
# tier of 2,500/day. Two properties make caching very effective here:
#
#   * Controllers don't move. An ATC position re-geocodes to the same answer
#     forever, so after the first lookup every refresh is a cache hit.
#   * A place name is coarse. Rounding coordinates to ~5 km still yields the
#     same city/state/country string, so cruising aircraft hit the cache for
#     several consecutive refreshes too.
#
# Entries are held for a day and the map is LRU-capped so a busy network
# can't grow it without bound.
_PRECISION = 2          # decimal degrees -> ~1.1 km at the equator
_TTL_SECONDS = 24 * 60 * 60
_MAX_ENTRIES = 4096

_cache: "OrderedDict[tuple, tuple]" = OrderedDict()

UNKNOWN = "Unknown location"


def _cache_key(lat: float, lon: float):
    return (round(float(lat), _PRECISION), round(float(lon), _PRECISION))


def _cache_get(key):
    hit = _cache.get(key)
    if hit is None:
        return None
    value, stored_at = hit
    if time.time() - stored_at > _TTL_SECONDS:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return value


def _cache_put(key, value):
    _cache[key] = (value, time.time())
    _cache.move_to_end(key)
    while len(_cache) > _MAX_ENTRIES:
        _cache.popitem(last=False)


def cache_stats():
    """(entries, capacity) -- for debugging quota behaviour."""
    return len(_cache), _MAX_ENTRIES


def _format(components):
    water = components.get("body_of_water")
    city = components.get("city") or components.get("town") or components.get("village")
    state = components.get("state") or components.get("province")
    country = components.get("country")

    if water:
        return f"Over the {water}"
    elif city and state and country:
        return f"{city}, {state}, {country}"
    elif state and country:
        return f"{state}, {country}"
    elif country:
        return country
    return UNKNOWN


async def reverse_geocode(lat: float, lon: float) -> str:
    """
    Returns a general location name (city/state/country or ocean) from
    coordinates. Cached -- see the note above.
    """
    if lat is None or lon is None:
        return UNKNOWN

    key = _cache_key(lat, lon)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    if not OPENCAGE_KEY:
        # No key configured: don't burn a request that can only 401, and
        # don't cache the miss as though it were an answer.
        return UNKNOWN

    url = (
        f"https://api.opencagedata.com/geocode/v1/json?q={lat}+{lon}"
        f"&key={OPENCAGE_KEY}&no_annotations=0&language=en"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    # 402 = quota exhausted, 429 = rate limited. Surface it in
                    # the log; the embed just shows "Unknown location".
                    print(f"[geo] opencage returned {resp.status}")
                    return UNKNOWN
                data = await resp.json()
    except Exception as e:
        print(f"[geo] reverse geocode failed: {type(e).__name__}: {e}")
        return UNKNOWN

    results = data.get("results") or []
    if not results:
        # A real answer -- these coordinates genuinely resolve to nothing.
        # Worth caching so we don't re-ask on every refresh.
        _cache_put(key, UNKNOWN)
        return UNKNOWN

    location = _format(results[0].get("components", {}))
    _cache_put(key, location)
    return location
