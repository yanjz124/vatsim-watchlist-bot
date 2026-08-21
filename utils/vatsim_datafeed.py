# utils/vatsim_datafeed.py
"""Backward-compatible shims that delegate to the centralized client
in utils.vatsim_api. New code should import vatsim_apis directly."""

from .vatsim_api import vatsim_apis

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"


async def fetch_vatsim_data():
    """Return cached VATSIM datafeed (shared across all callers within ~14s)."""
    return await vatsim_apis.get_datafeed()


async def fetch_user_name(cid, session=None):
    """Return 'fname lname' for a CID via VATUSA. session arg is ignored
    (the central client manages its own session)."""
    return await vatsim_apis.get_user_name(cid)
