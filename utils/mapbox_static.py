import aiohttp
from io import BytesIO
from config import MAPBOX
import polyline
import math

BASE_URL = "https://api.mapbox.com/styles/v1/mapbox/streets-v12/static"


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


async def generate_map_image(center_lat, center_lon, pins=None, path_coords=None, zoom=None, width=600, height=400):
    layers = []

    # Add path if available
    if path_coords and len(path_coords) >= 2:
        encoded = polyline.encode(path_coords, precision=5)
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
        f"{BASE_URL}/{layer_str}/{center_lon},{center_lat},{zoom}/{width}x{height}"
        f"?access_token={MAPBOX}"
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                error_msg = f"Mapbox Error {resp.status}:\n```{error_text[:1000]}```"
                error_url = f"URL:\n```{url[:1000]}```"
                return error_msg + "\n" + error_url
            data = await resp.read()
            return BytesIO(data)
