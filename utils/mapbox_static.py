import aiohttp
from io import BytesIO
from config import MAPBOX
import polyline
from urllib.parse import quote
import math

_STYLE_ROOT = "https://api.mapbox.com/styles/v1/mapbox"
DEFAULT_STYLE = "streets-v12"
BASE_URL = f"{_STYLE_ROOT}/{DEFAULT_STYLE}/static"


def _base_url(style=None):
    """Static-image endpoint for a Mapbox style.

    streets-v12 is the right default for a position card, but its yellow road
    casings sit right on top of the low-altitude end of the track gradient, so
    a coloured track over a dense street map can be genuinely hard to pick out.
    Callers drawing a track as the subject of the image should pass a muted
    style such as "light-v11".
    """
    return f"{_STYLE_ROOT}/{style or DEFAULT_STYLE}/static"


def compute_zoom(points, width=600, height=400, padding_km=25, min_zoom=4, max_zoom=15):
    if not points or len(points) < 2:
        return 7  # default zoom

    # Use only first and last points for a meaningful path-based zoom
    (lat1, lon1), (lat2, lon2) = points[0], points[-1]

    # Approximate distance between the two
    lat_km = abs(lat2 - lat1) * 111  # degrees to km
    lon_km = abs(lon2 - lon1) * 111 * math.cos(math.radians((lat1 + lat2) / 2))
    total_distance_km = math.sqrt(lat_km ** 2 + lon_km ** 2) + padding_km

    # Compute zoom level based on Earth circumference (heuristic)
    zoom = math.log2(40075 / total_distance_km)
    return int(max(min(zoom, max_zoom), min_zoom))


def compute_zoom_between_two_points(start, end, width=600, height=400, padding=2, min_zoom=4, max_zoom=15, initial_zoom=8):
    if not start or not end:
        return initial_zoom

    lat1, lon1 = start
    lat2, lon2 = end

    # Compute degree differences
    lat_diff = abs(lat2 - lat1)
    lon_diff = abs(lon2 - lon1)

    # Convert to approximate kilometers
    lat_km = lat_diff * 111  # 1 degree lat ≈ 111 km
    lon_km = lon_diff * 111 * math.cos(math.radians((lat1 + lat2) / 2))

    # Double the distance since only one side of the path is visible
    distance_km = math.sqrt(lat_km**2 + lon_km**2) * 2 * (1 + padding)

    # Compute zoom level
    zoom = math.log2(40075 / max(distance_km, 1)) + 1.5
    return int(max(min(zoom, max_zoom), min_zoom))


# FR24-style altitude color stops. Smooth gradient is interpolated
# between these in RGB space, then quantized so adjacent segments with
# nearly identical altitudes share a Mapbox layer.
_GRADIENT_STOPS = [
    (100,   (255, 255, 255)),   # ground / unknown -> white
    (5000,  (255, 255,   0)),   # yellow
    (15000, (  0, 255,   0)),   # green
    (25000, (  0, 200, 255)),   # cyan
    (35000, (  0,  80, 255)),   # blue
    (45000, (180,   0, 255)),   # purple
    (55000, (255,   0, 100)),   # red
]
_COLOR_QUANTIZE_STEP = 16   # 16 steps per channel = 16 distinct shades along the ramp


def altitude_gradient_color(alt_ft):
    """Interpolate a smooth color from _GRADIENT_STOPS for the given
    altitude in feet, then quantize each channel so adjacent segments
    with similar altitudes share a color (and merge into one Mapbox
    layer)."""
    if alt_ft is None or alt_ft <= _GRADIENT_STOPS[0][0]:
        r, g, b = _GRADIENT_STOPS[0][1]
    elif alt_ft >= _GRADIENT_STOPS[-1][0]:
        r, g, b = _GRADIENT_STOPS[-1][1]
    else:
        for (a1, c1), (a2, c2) in zip(_GRADIENT_STOPS, _GRADIENT_STOPS[1:]):
            if a1 <= alt_ft <= a2:
                t = (alt_ft - a1) / (a2 - a1) if a2 != a1 else 0.0
                r = int(round(c1[0] + t * (c2[0] - c1[0])))
                g = int(round(c1[1] + t * (c2[1] - c1[1])))
                b = int(round(c1[2] + t * (c2[2] - c1[2])))
                break

    step = _COLOR_QUANTIZE_STEP
    r = min(255, (r // step) * step)
    g = min(255, (g // step) * step)
    b = min(255, (b // step) * step)
    return f"{r:02x}{g:02x}{b:02x}"


def _altitude_colored_path_layers(path_coords, path_altitudes):
    """Emit Mapbox `path-` layers split by interpolated altitude color.
    Consecutive segments with the same quantized color get merged into
    one polyline so the URL stays short even on a 60-point trail."""
    layers = []
    if not path_coords or len(path_coords) < 2:
        return layers

    segments = []   # list of [color, [point, point, ...]]
    for i in range(len(path_coords) - 1):
        a1 = path_altitudes[i] if i < len(path_altitudes) else None
        a2 = path_altitudes[i + 1] if i + 1 < len(path_altitudes) else None
        if a1 is None and a2 is None:
            avg = None
        elif a1 is None:
            avg = a2
        elif a2 is None:
            avg = a1
        else:
            avg = (a1 + a2) / 2.0
        color = altitude_gradient_color(avg)
        if segments and segments[-1][0] == color:
            segments[-1][1].append(path_coords[i + 1])
        else:
            segments.append([color, [path_coords[i], path_coords[i + 1]]])

    for color, pts in segments:
        encoded = _encode_path(pts)
        layers.append(f"path-3+{color}-0.9({encoded})")
    return layers


def polygon_layer(ring, stroke="f43f5e", stroke_width=2, stroke_opacity=0.9,
                  fill="f43f5e", fill_opacity=0.18):
    """Encode a closed (lat, lon) ring as a filled Mapbox static overlay.

    Mapbox caps the request URL at 8,192 characters, so rings have to be
    simplified before they get here -- a few dozen points is the practical
    budget once a track and pins share the same URL.
    """
    if not ring or len(ring) < 3:
        return None
    encoded = _encode_path([(float(a), float(b)) for a, b in ring])
    return (f"path-{stroke_width}+{stroke}-{stroke_opacity}"
            f"+{fill}-{fill_opacity}({encoded})")


async def generate_map_image(center_lat, center_lon, pins=None,
                             path_coords=None, path_altitudes=None,
                             zoom=None, width=600, height=400,
                             underlays=None, style=None):
    """Render a Mapbox static image, or None if one can't be produced.

    Always returns BytesIO or None -- never an error string. The request URL
    carries the access token as a query parameter, so nothing derived from it
    may be handed back to a caller.
    """
    if not MAPBOX:
        return None

    # Overlays render in URL order, so anything passed as an underlay is drawn
    # first and therefore sits beneath the track and pins.
    layers = [l for l in (underlays or []) if l]

    # Add path if available. Mapbox Static Images allows at most 100 overlay
    # features and an 8192-char URL. A noisy/long altitude profile can explode
    # into many tiny per-color `path-` segments (one overlay each) and blow past
    # the feature limit, so the whole request fails and no map renders. Prefer
    # the altitude-colored path only while it stays within a safe budget;
    # otherwise fall back to a single simple polyline so the map still renders.
    if path_coords and len(path_coords) >= 2:
        alt_layers = []
        if path_altitudes and len(path_altitudes) == len(path_coords):
            alt_layers = _altitude_colored_path_layers(path_coords, path_altitudes)
        _MAX_PATH_SEGMENTS = 40
        if alt_layers and len(alt_layers) <= _MAX_PATH_SEGMENTS:
            layers.extend(alt_layers)
        else:
            encoded = _encode_path(path_coords)
            layers.append(f"path-3+0000ff-0.9({encoded})")

    # Add pins
    if pins:
        if len(pins) == 1:
            lat, lon = pins[0]
            layers.append(f"pin-s-airport+ff0000({lon},{lat})")
        elif len(pins) >= 2:
            start_lat, start_lon = pins[0]
            end_lat, end_lon = pins[-1]
            layers.append(f"pin-s-airport+00ff00({start_lon},{start_lat})")
            layers.append(f"pin-s-airport+ff0000({end_lon},{end_lat})")

    if not layers:
        # Fallback marker
        layers.append(f"pin-s-airport+ff0000({center_lon},{center_lat})")

    # Compute zoom if not provided
    if zoom is None:
        all_points = (pins or []) + (path_coords or [])
        zoom = compute_zoom(all_points) if len(all_points) > 1 else 7

    layer_str = ",".join(layers)
    url = (
        f"{_base_url(style)}/{layer_str}/{center_lon},{center_lat},{zoom}/{width}x{height}"
        f"?access_token={MAPBOX}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    # Log, never return: the URL carries ?access_token=, and
                    # callers have historically sent this value straight to
                    # Discord. 429s become the common case once the bot is in
                    # more than a handful of servers.
                    error_text = await resp.text()
                    print(f'[mapbox] static image request failed '
                          f'({resp.status}): {error_text[:300]}')
                    return None
                return BytesIO(await resp.read())
    except Exception as e:
        print(f'[mapbox] static image request errored: {type(e).__name__}: {e}')
        return None


def _encode_path(points):
    """Polyline-encode points for use inside a Mapbox overlay.

    The encoding alphabet is ASCII 63..126, which includes '?' and '#'. Dropped
    raw into the URL path, a '?' makes everything after it the query string --
    so access_token is lost and Mapbox answers 401 "Direct access not allowed".
    It is intermittent by nature: whether a given track encodes to a '?' is
    pure chance, so most maps render and the occasional one silently doesn't.
    Percent-encode the payload; the surrounding overlay syntax stays literal.
    """
    return quote(polyline.encode(points, precision=5), safe="")


def _lat_to_mercator_y(lat):
    """Clamp latitude to the web Mercator valid range and return Y (radians)."""
    lat = max(-85.05112878, min(85.05112878, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _mercator_y_to_lat(y):
    """Inverse of _lat_to_mercator_y."""
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def _enclosing_lon_arc(lons):
    """Return (center_lon, span_deg) for the smallest arc on a circle that
    encloses every input longitude. Handles antimeridian wrap so e.g.
    [+170, -170] resolves to a 20° arc centered on 180 rather than a 340°
    span centered on 0. Span is 0 when all inputs coincide."""
    if not lons:
        return 0.0, 0.0
    if len(set(lons)) == 1:
        return lons[0], 0.0

    sorted_lons = sorted(lons)
    direct_span = sorted_lons[-1] - sorted_lons[0]
    wrap_gap = 360.0 - direct_span

    max_gap = 0.0
    max_gap_idx = -1
    for i in range(len(sorted_lons) - 1):
        gap = sorted_lons[i + 1] - sorted_lons[i]
        if gap > max_gap:
            max_gap = gap
            max_gap_idx = i

    if wrap_gap >= max_gap:
        # Pins sit in a contiguous arc that does not cross the dateline.
        return (sorted_lons[0] + sorted_lons[-1]) / 2.0, direct_span

    # The widest "hole" is between two adjacent pins — cut the circle there
    # and the enclosing arc wraps through ±180.
    span = 360.0 - max_gap
    start = sorted_lons[max_gap_idx + 1]
    end = sorted_lons[max_gap_idx] + 360.0
    center = (start + end) / 2.0
    if center > 180:
        center -= 360
    return center, span


async def generate_pins_map(
    pins,
    labels=None,
    width=600,
    height=400,
    color='ff0000',
    pin_size='l',
    zoom=None,
    center=None,
    min_zoom=0,
    max_zoom=7,
    padding_factor=1.2,
):
    """Draw pins on a Mapbox static map, auto-fitting center and zoom to all pins.

    pins: list of (lat, lon) tuples.
    labels: optional list (same length as pins) of pin labels; each entry may be
            a string matching [0-9]{1,2} or [a-z], or None for an unlabeled pin.
    pin_size: 'l' (large, supports labels) or 's' (small, no labels).
    zoom / center: explicit overrides. When omitted they are auto-computed
                   using web Mercator math and antimeridian-aware longitude
                   bounds so globally scattered pins fit via the shortest arc.

    Returns BytesIO on success, None on error or empty input.
    """
    if not pins:
        return None

    lats = [p[0] for p in pins]
    lons = [p[1] for p in pins]

    # Compute bounding box in web Mercator space, antimeridian-aware, so that
    # e.g. Kansas (−95°) + Tokyo (+140°) resolves to a ~220° arc centered on
    # the Pacific rather than a 246° span centered on Turkey.
    auto_center_lon, lon_span = _enclosing_lon_arc(lons)
    y_min = _lat_to_mercator_y(min(lats))
    y_max = _lat_to_mercator_y(max(lats))

    if center is None:
        center_lat = _mercator_y_to_lat((y_min + y_max) / 2)
        center_lon = auto_center_lon
    else:
        center_lat, center_lon = center

    if zoom is None:
        if len(pins) == 1:
            zoom = max_zoom
        else:
            # Pixel-aware Mercator fit: at zoom z the world is TILE_SIZE·2^z
            # pixels wide, so we need lon_frac·TILE_SIZE·2^z ≤ width and
            # likewise for height. Take the min so both axes fit.
            TILE_SIZE = 256
            lon_frac = max(lon_span / 360.0, 1e-9) * padding_factor
            lat_frac = max((y_max - y_min) / (2 * math.pi), 1e-9) * padding_factor
            zoom_x = math.log2(width / (TILE_SIZE * lon_frac))
            zoom_y = math.log2(height / (TILE_SIZE * lat_frac))
            zoom_fit = min(zoom_x, zoom_y)
            zoom = max(min_zoom, min(max_zoom, round(zoom_fit, 2)))

    if not MAPBOX:
        return None

    layers = []
    for i, (lat, lon) in enumerate(pins):
        label_suffix = ""
        if labels and i < len(labels) and labels[i] is not None:
            label_suffix = f"-{labels[i]}"
        layers.append(f"pin-{pin_size}{label_suffix}+{color}({lon},{lat})")

    layer_str = ",".join(layers)
    url = (
        f"{BASE_URL}/{layer_str}/{center_lon},{center_lat},{zoom}/{width}x{height}"
        f"?access_token={MAPBOX}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return BytesIO(await resp.read())
    except Exception:
        return None
