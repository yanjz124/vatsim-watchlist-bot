import os
import time
from collections import OrderedDict

import aiohttp

OPENCAGE_KEY = os.getenv("OPENCAGE_KEY")

# Reverse geocoding is called once per position embed, and every monitor
# rebuilds its embed on a fixed refresh interval, so the request rate scales
# with (guilds x watched entries online) against a free tier of 2,500/day.
#
# What the cache actually saves: only things that hold still. A controller
# never moves, so after one lookup every subsequent refresh is a hit -- and
# controllers sit for hours. A moving aircraft is the opposite: at 450 kts it
# covers ~70 km between 5-minute refreshes, so a fine-grained cell misses
# every single time. The fix is to stop asking for detail we don't need: at
# cruise the answer is reported region-only, which makes a ~170 km cell safe
# and lands around 58% cache hits on a 450 kt leg. Below 18,000 ft the cell
# stays fine-grained and city-level, and effectively never hits -- which is
# the right trade, since that's where the detail is worth paying for.
#
# Because the pilot cost is effectively unbounded -- it scales with however
# many servers invite the bot -- there is also a hard daily ceiling. Once it
# trips, lookups stop and embeds simply omit the location line rather than
# running up a bill on the host's account.
_TTL_SECONDS = 24 * 60 * 60
_MAX_ENTRIES = 4096

# Cache cell size by altitude band: (min_altitude_ft, cell size in degrees).
# 0.01 deg ~ 1.1 km, 0.1 deg ~ 11 km, 2.0 deg ~ 170 km of longitude at
# mid-latitudes.
# At cruise we deliberately report region-only (see _format), which is both
# more truthful -- an aircraft at FL370 is not "in" a city -- and what makes
# a genuinely coarse cell safe. 2 degrees is ~170 km of longitude at
# mid-latitudes, wide enough that a 450 kt aircraft stays inside it for
# several consecutive refreshes instead of missing every time.
_PRECISION_BANDS = (
    (18000, 2.0),   # cruise: region only, coarse cell
    (5000,  0.1),   # climb/descent: ~11 km
)
_COARSE_ABOVE_FT = 18000
_PRECISION_DEFAULT = 0.01   # low level, ground, and controllers

# Daily request ceiling. OpenCage's free tier is 2,500/day; default a little
# under so a shared instance can't quietly cross into paid usage.
_DAILY_CAP = int(os.getenv("OPENCAGE_DAILY_CAP", "2000"))

_cache: "OrderedDict[tuple, tuple]" = OrderedDict()
_spend = {"day": None, "count": 0, "capped_logged": False}

UNKNOWN = "Unknown location"


def _cell_size(altitude_ft):
    try:
        alt = float(altitude_ft)
    except (TypeError, ValueError):
        return _PRECISION_DEFAULT
    for floor, size in _PRECISION_BANDS:
        if alt >= floor:
            return size
    return _PRECISION_DEFAULT


def _quantize(value, size):
    return round(round(float(value) / size) * size, 4)


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def _budget_available():
    """True if we may spend a request. Resets at UTC midnight."""
    day = _today()
    if _spend["day"] != day:
        _spend.update(day=day, count=0, capped_logged=False)
    if _spend["count"] >= _DAILY_CAP:
        if not _spend["capped_logged"]:
            print(f"[geo] daily OpenCage cap of {_DAILY_CAP} reached; "
                  f"omitting location until UTC midnight")
            _spend["capped_logged"] = True
        return False
    return True


def quota_stats():
    """(used_today, cap) -- for !sys style reporting."""
    if _spend["day"] != _today():
        return 0, _DAILY_CAP
    return _spend["count"], _DAILY_CAP


def _cache_key(lat: float, lon: float, altitude_ft=None):
    size = _cell_size(altitude_ft)
    return (_quantize(lat, size), _quantize(lon, size), size)


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


def _is_coarse(altitude_ft):
    try:
        return float(altitude_ft) >= _COARSE_ABOVE_FT
    except (TypeError, ValueError):
        return False


def _format(components, coarse=False):
    water = components.get("body_of_water")
    city = components.get("city") or components.get("town") or components.get("village")
    state = components.get("state") or components.get("province")
    country = components.get("country")

    if water:
        return f"Over the {water}"
    if coarse:
        # Region only: the city under a cruising aircraft is noise, and
        # omitting it keeps the answer stable across a wide cache cell.
        if state and country:
            return f"{state}, {country}"
        return country or UNKNOWN
    if city and state and country:
        return f"{city}, {state}, {country}"
    if state and country:
        return f"{state}, {country}"
    if country:
        return country
    return UNKNOWN


async def reverse_geocode(lat: float, lon: float, altitude_ft=None) -> str:
    """
    Returns a general location name (city/state/country or ocean) from
    coordinates, or UNKNOWN when unavailable. Cached -- see the note above.

    `altitude_ft` only widens the cache cell: higher means a coarser cell,
    because at altitude the answer is a region rather than a street. Callers
    that don't know the altitude get the finest cell.
    """
    if lat is None or lon is None:
        return UNKNOWN

    key = _cache_key(lat, lon, altitude_ft)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    if not OPENCAGE_KEY:
        # No key configured: don't burn a request that can only 401, and
        # don't cache the miss as though it were an answer.
        return UNKNOWN

    if not _budget_available():
        # Over the daily ceiling. Return without caching, so the answer comes
        # back properly once the budget resets rather than being pinned to
        # UNKNOWN for the rest of the TTL.
        return UNKNOWN

    url = (
        f"https://api.opencagedata.com/geocode/v1/json?q={lat}+{lon}"
        f"&key={OPENCAGE_KEY}&no_annotations=0&language=en"
    )

    _spend["count"] += 1
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

    location = _format(results[0].get("components", {}), coarse=_is_coarse(altitude_ft))
    _cache_put(key, location)
    return location
