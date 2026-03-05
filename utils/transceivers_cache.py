# utils/transceivers_cache.py

import aiohttp
import asyncio
from typing import Optional, List

TRANSCEIVERS_URL = "https://data.vatsim.net/v3/transceivers-data.json"

# Global cache
_transceivers_cache = []
_cache_lock = asyncio.Lock()
_cache_task = None


async def _fetch_transceivers_loop():
    """Background task that fetches transceivers data every 15 seconds."""
    global _transceivers_cache

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(TRANSCEIVERS_URL, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        async with _cache_lock:
                            _transceivers_cache = data
                    else:
                        print(f"[Transceivers Cache] Failed to fetch: HTTP {response.status}")
        except Exception as e:
            print(f"[Transceivers Cache] Error fetching data: {e}")

        await asyncio.sleep(15)


def start_transceivers_cache():
    """Start the background cache updater task."""
    global _cache_task
    if _cache_task is None or _cache_task.done():
        _cache_task = asyncio.create_task(_fetch_transceivers_loop())


async def get_transceivers_data() -> list:
    """Get the cached transceivers data."""
    async with _cache_lock:
        return _transceivers_cache.copy()


async def get_frequencies_for_callsign(callsign: str) -> Optional[List[str]]:
    """Get formatted frequencies for a given callsign from the cache."""
    data = await get_transceivers_data()

    for entry in data:
        if entry.get('callsign', '').upper() == callsign.upper():
            transceivers = entry.get('transceivers', [])
            if not transceivers:
                return None

            frequencies = []
            for t in transceivers:
                freq_hz = t.get('frequency', 0)
                freq_mhz = freq_hz / 1_000_000
                frequencies.append(f"{freq_mhz:.3f}")

            return frequencies

    return None
