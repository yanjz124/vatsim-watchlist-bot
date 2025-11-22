import aiohttp
import requests

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"


async def fetch_vatsim_data():
    """Fetch and return the full VATSIM data feed as a dictionary."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(VATSIM_DATA_URL) as response:
                if response.status == 429:
                    raise Exception("Rate limited by VATSIM API (429)")
                elif response.status != 200:
                    raise Exception(f"Failed to fetch data: HTTP {response.status}")
                return await response.json()
    except Exception as e:
        print(f"[VATSIM Fetch Error] {e}")
        return None


def fetch_transceivers_data():
    """Fetch and return the transceivers data."""
    url = "https://data.vatsim.net/v3/transceivers-data.json"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def get_frequencies_for_callsign(callsign, controller_data):
    """Return a list of frequency strings for a given controller callsign."""
    for entry in controller_data:
        if entry['callsign'].upper() == callsign.upper():
            transceivers = entry.get('transceivers', [])
            return [f"{t['frequency'] / 1_000_000:.3f}" for t in transceivers]
    return None


async def fetch_user_name(cid, session=None):
    """Return the full name for a given CID using VATUSA API."""
    if cid in ('N/A', 0, None):
        return 'N/A'

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        url = f"https://api.vatusa.net/v2/user/{cid}"
        timeout = aiohttp.ClientTimeout(total=5)
        async with session.get(url, timeout=timeout) as response:
            if response.status == 200:
                data = await response.json()
                user_data = data.get('data', {})
                return f"{user_data.get('fname', '')} {user_data.get('lname', '')}".strip()
    except Exception:
        pass
    finally:
        if close_session:
            await session.close()

    return "N/A"
