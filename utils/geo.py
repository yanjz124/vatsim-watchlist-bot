import aiohttp
import os

# Set your OpenCage API key here or from environment variable
OPENCAGE_KEY = os.getenv("OPENCAGE_KEY")

async def reverse_geocode(lat: float, lon: float) -> str:
    """
    Returns a general location name (city/state/country or ocean) from coordinates.
    """
    url = f"https://api.opencagedata.com/geocode/v1/json?q={lat}+{lon}&key={OPENCAGE_KEY}&no_annotations=0&language=en"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return "Unknown location"
            data = await resp.json()

    if not data.get("results"):
        return "Unknown location"

    result = data["results"][0]
    components = result.get("components", {})
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
    else:
        return "Unknown location"
