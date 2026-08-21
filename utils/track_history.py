"""In-memory per-CID position history for the map embed trail.

Bounded both per-CID (max points) and globally (LRU cap on CIDs) so memory
stays flat. Volatile by design — restarts clear history.

Reset rules: the stored trail is wiped when a CID switches callsign (e.g.
disconnect then reconnect on a different aircraft) or when a single sample
jumps farther than _TELEPORT_DISTANCE_NM from the previous one (a real jet
can't cover that distance in the ~5-min sample interval, so it's almost
certainly a reconnect/teleport).
"""

import math
import time
from collections import OrderedDict, deque


_MAX_POINTS_PER_TRACK = 60       # ~5h at the 5-min PILOT_REFRESH_INTERVAL
_MAX_TRACKS = 500                # LRU cap across all CIDs
_MIN_POINT_DISTANCE_NM = 0.5     # skip a sample if the pilot barely moved
_TELEPORT_DISTANCE_NM = 200      # a single hop farther than this resets the trail
_DEFAULT_MAX_AGE_SECONDS = 6 * 3600

_tracks = OrderedDict()


def _distance_nm(lat1, lon1, lat2, lon2):
    lat_km = (lat2 - lat1) * 111.0
    lon_km = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
    return math.sqrt(lat_km * lat_km + lon_km * lon_km) / 1.852


def _new_track(callsign):
    return {'callsign': callsign,
            'points': deque(maxlen=_MAX_POINTS_PER_TRACK)}


def record_position(cid, lat, lon, *, callsign=None, altitude=None):
    """Append (lat, lon, altitude, ts) for this CID. No-op if cid/lat/lon
    missing or the new sample is within _MIN_POINT_DISTANCE_NM of the last.

    Resets the trail before appending when:
      - the callsign changed since the last sample (different connection), or
      - the new sample is more than _TELEPORT_DISTANCE_NM from the last
        (likely a disconnect + reconnect elsewhere)."""
    if cid is None or lat is None or lon is None:
        return
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return

    try:
        alt = int(altitude) if altitude not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        alt = None

    track = _tracks.pop(cid, None)
    if track is None:
        track = _new_track(callsign)
    elif track.get('callsign') != callsign:
        # Different connection -> start fresh.
        track = _new_track(callsign)
    elif track['points']:
        last_lat, last_lon, _, _ = track['points'][-1]
        dist = _distance_nm(last_lat, last_lon, lat, lon)
        if dist < _MIN_POINT_DISTANCE_NM:
            # Refresh LRU position but skip duplicate-ish sample.
            _tracks[cid] = track
            return
        if dist > _TELEPORT_DISTANCE_NM:
            # Teleport / reconnect — wipe history before the new sample.
            track = _new_track(callsign)

    track['points'].append((float(lat), float(lon), alt, int(time.time())))
    _tracks[cid] = track

    while len(_tracks) > _MAX_TRACKS:
        _tracks.popitem(last=False)


def get_track(cid, max_age_seconds=_DEFAULT_MAX_AGE_SECONDS):
    """Return [(lat, lon, altitude_ft_or_None), ...] for this CID, dropping
    samples older than max_age_seconds. Empty list if unknown."""
    if cid is None:
        return []
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return []
    track = _tracks.get(cid)
    if not track:
        return []
    cutoff = int(time.time()) - max_age_seconds
    return [(lat, lon, alt)
            for lat, lon, alt, ts in track['points']
            if ts >= cutoff]


def clear_track(cid):
    if cid is None:
        return
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return
    _tracks.pop(cid, None)


def track_bbox_zoom(points, padding=1.3, min_zoom=4, max_zoom=9, fallback=7):
    """Pick a zoom level that fits the track bbox. Accepts (lat, lon) or
    (lat, lon, alt) tuples — only the first two are used. Falls back to
    ``fallback`` when the track is empty or essentially a single point."""
    if not points or len(points) < 2:
        return fallback
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_span = max(lats) - min(lats)
    lon_span = max(lons) - min(lons)
    if lat_span < 0.01 and lon_span < 0.01:
        return fallback
    avg_lat = sum(lats) / len(lats)
    lat_km = lat_span * 111.0
    lon_km = lon_span * 111.0 * math.cos(math.radians(avg_lat))
    distance_km = max(math.sqrt(lat_km * lat_km + lon_km * lon_km), 1.0) * padding
    zoom = math.log2(40075.0 / distance_km) - 1
    return int(max(min(zoom, max_zoom), min_zoom))


def _zoom_for_radius_nm(radius_nm, min_zoom=4, max_zoom=11):
    """Return the zoom level whose visible viewport spans ~2 * radius_nm."""
    diameter_km = max(2 * radius_nm * 1.852, 1.0)
    z = math.log2(40075.0 / diameter_km) - 1
    return int(max(min_zoom, min(max_zoom, z)))


def smart_zoom_for_track(track, current_lat, current_lon,
                         groundspeed_kts=None, heading_deg=None,
                         look_ahead_min=12, min_zoom=4, max_zoom=11,
                         fallback=7):
    """Pick a zoom that combines:
      - bbox of the recorded trail,
      - a look-ahead projection in the direction of flight,
      - a minimum visible radius scaled by groundspeed,
      - speed-aware overrides for taxi (zoom in) vs. cruise (zoom out).

    Returns a zoom number in [min_zoom, max_zoom]. Lower = wider view."""
    gs = groundspeed_kts if isinstance(groundspeed_kts, (int, float)) else None
    hd = heading_deg if isinstance(heading_deg, (int, float)) else None

    # Slow-speed overrides: skip the bbox math, show airport detail.
    # (Only when we actually have a groundspeed reading — None falls through.)
    if gs is not None:
        if gs < 5:
            return min(max_zoom, 11)   # parked
        if gs < 50:
            return min(max_zoom, 10)   # taxi / final

    # Build the point set we'll fit to (lat/lon only).
    points = [(p[0], p[1]) for p in (track or [])]

    # Add a look-ahead point in the direction of flight so the camera
    # sits behind the aircraft, FR24-style. Short hop at low speeds,
    # longer at cruise.
    if (hd is not None and gs and gs > 0
            and current_lat is not None and current_lon is not None):
        look_ahead_nm = max(30.0, gs * (look_ahead_min / 60.0))
        nm_per_deg_lat = 60.0
        rad = math.radians(hd)
        d_lat = (look_ahead_nm * math.cos(rad)) / nm_per_deg_lat
        cos_lat = max(0.01, math.cos(math.radians(current_lat)))
        d_lon = (look_ahead_nm * math.sin(rad)) / (nm_per_deg_lat * cos_lat)
        points.append((current_lat + d_lat, current_lon + d_lon))

    # bbox zoom over the (possibly augmented) point set.
    if points:
        bbox_zoom = track_bbox_zoom(points, fallback=fallback,
                                    min_zoom=min_zoom, max_zoom=max_zoom)
    else:
        bbox_zoom = fallback

    # Minimum visible radius, scaled by groundspeed.
    if gs and gs > 0:
        min_radius_nm = max(20.0, gs * 0.2)
    else:
        min_radius_nm = 50.0
    radius_zoom = _zoom_for_radius_nm(min_radius_nm,
                                      min_zoom=min_zoom, max_zoom=max_zoom)

    # Wider (lower) of the two — guarantees min_radius_nm of context.
    zoom = min(bbox_zoom, radius_zoom)

    # Cruise cap: don't zoom in too tight when fast.
    if gs and gs > 300:
        zoom = min(zoom, 6)

    return int(max(min_zoom, min(max_zoom, zoom)))
