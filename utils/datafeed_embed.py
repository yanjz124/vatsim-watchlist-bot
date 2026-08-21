"""Common formatter for VATSIM client status embeds.

Used by anything that needs to render a 'who's online' card — manual
lookups (!cid, !usa), monitor notifications (callsign, CID, type, sup,
coc keyword), etc. Produces a (discord.Embed, optional discord.File)
pair so the caller can attach the position map.
"""

import discord
from dateutil import parser
from datetime import timezone

from utils import fetch_vatsim_data, get_frequencies_for_callsign
from utils.geo import reverse_geocode, UNKNOWN
from utils.mapbox_static import generate_map_image
from utils.track_history import (
    record_position, get_track, smart_zoom_for_track,
)
from config import facility


# Human-readable labels used by the change-summary footer.
_FIELD_NAMES = {
    "initial": "initial connection",
    "position": "position/map",
    "callsign": "callsign",
    "rating": "rating",
    "server": "server",
    "start_time": "logon time",
    "frequency": "frequency",
    "facility": "facility",
    "visual_range": "visual range",
    "text_atis": "ATIS",
    "last_updated": "controller update",
    "atis_code": "ATIS code",
    "transponder": "squawk",
    "assigned_transponder": "assigned squawk",
    "aircraft": "aircraft",
    "flight_rules": "flight rules",
    "departure": "departure",
    "arrival": "arrival",
    "alternate": "alternate",
    "cruise_tas": "cruise speed",
    "altitude": "altitude",
    "deptime": "departure time",
    "enroute_time": "enroute time",
    "fuel_time": "fuel time",
    "route": "route",
    "remarks": "remarks",
}


# ── small helpers ────────────────────────────────────────────────────


def _format_vatsim_time(s):
    """Render a VATSIM ISO timestamp as 'YYYY-MM-DD HH:MMZ\\n<t:ts:R>'.
    Returns the raw string on parse failure, 'N/A' if empty."""
    if not s:
        return "N/A"
    try:
        dt = parser.isoparse(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return f"{dt.strftime('%Y-%m-%d %H:%MZ')}\n<t:{int(dt.timestamp())}:R>"
    except (ValueError, TypeError):
        return s


def _format_qnh(live_entry):
    """Return a one-line QNH string, or empty if both values missing."""
    inhg = live_entry.get("qnh_i_hg", "N/A")
    mb = live_entry.get("qnh_mb", "N/A")
    parts = []
    if inhg != "N/A":
        parts.append(f"{inhg} inHg")
    if mb != "N/A":
        parts.append(f"{mb} hPa")
    return f"QNH: {' / '.join(parts)}" if parts else ""


def _pick_aircraft(fp):
    """Aircraft display preference: short -> faa -> raw -> 'N/A'."""
    return next((fp.get(k) for k in ("aircraft_short", "aircraft_faa", "aircraft")
                 if fp.get(k)), "N/A")


# ── data feed access ────────────────────────────────────────────────


async def _get_live_entry(cid):
    """Find the live data-feed entry for a CID (controller or pilot)."""
    try:
        data = await fetch_vatsim_data()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    for entry in data.get("controllers", []):
        if entry.get("cid") == cid:
            return entry
    for entry in data.get("pilots", []):
        if entry.get("cid") == cid:
            return entry
    return None


# ── frequencies ─────────────────────────────────────────────────────


async def _add_frequencies_field(embed, callsign, *,
                                 field_name="Frequencies",
                                 atc_fallback=None,
                                 single_line=False,
                                 inline=True):
    """Look up AFV transceiver frequencies for ``callsign`` and add a field.

    atc_fallback: pass the controller's client_data dict to fall back to
        client_data['frequency'] when AFV returns nothing.
    single_line: format every freq comma-separated on one line (used for
        pilots). Otherwise the first freq is primary and the rest go in
        parentheses (used for ATC).
    """
    try:
        afv = await get_frequencies_for_callsign(callsign)
    except Exception as e:
        print(f"[build_status_embed] AFV freq fetch failed for {callsign}: {e}")
        afv = None

    if afv:
        unique = list(dict.fromkeys(afv))
        if single_line or len(unique) == 1:
            value = ", ".join(unique) if single_line else unique[0]
        else:
            value = f"{unique[0]} ({', '.join(unique[1:])})"
        embed.add_field(name=field_name, value=value,
                        inline=inline and not single_line)
        return

    if atc_fallback is not None:
        embed.add_field(name=field_name,
                        value=atc_fallback.get("frequency", "N/A"),
                        inline=True)


# ── per-role field blocks ───────────────────────────────────────────


async def _add_atc_fields(embed, client_data):
    callsign = client_data.get("callsign", "N/A")
    await _add_frequencies_field(embed, callsign,
                                 field_name="Frequency",
                                 atc_fallback=client_data)

    facility_id = client_data.get("facility", "N/A")
    embed.add_field(name="Facility",
                    value=facility.get(facility_id, f"Unknown ({facility_id})"),
                    inline=True)
    embed.add_field(name="Visual Range",
                    value=f'{client_data.get("visual_range", "N/A")} NM',
                    inline=True)

    atis = client_data.get("text_atis", [])
    embed.add_field(name="Text ATIS",
                    value="\n".join(atis) if atis else "N/A",
                    inline=False)

    embed.add_field(name="Logon Time",
                    value=_format_vatsim_time(client_data.get("logon_time")),
                    inline=True)
    embed.add_field(name="Last Updated",
                    value=_format_vatsim_time(client_data.get("last_updated")),
                    inline=True)


def _add_pilot_fields(embed, client_data):
    embed.add_field(name="Start Time",
                    value=_format_vatsim_time(client_data.get("logon_time")),
                    inline=True)

    fp = client_data.get("flight_plan")
    if not fp:
        embed.add_field(name="Flight Plan", value="No flight plan filed",
                        inline=False)
        return

    # Row 1 — Aircraft / Flight Type / Altitude
    embed.add_field(name="Aircraft", value=_pick_aircraft(fp), inline=True)
    embed.add_field(name="Flight Type",
                    value=f"{fp.get('flight_rules', 'N/A')}FR", inline=True)
    embed.add_field(name="Altitude", value=fp.get("altitude", "N/A"),
                    inline=True)
    # Row 2 — Departure / Arrival / Alternate
    embed.add_field(name="Departure", value=fp.get("departure", "N/A"),
                    inline=True)
    embed.add_field(name="Arrival", value=fp.get("arrival", "N/A"),
                    inline=True)
    embed.add_field(name="Alternate", value=fp.get("alternate", "N/A"),
                    inline=True)
    # Row 3 — Current Squawk / Assigned Squawk / Cruise Speed
    embed.add_field(name="Current Squawk",
                    value=client_data.get("transponder", "N/A"),
                    inline=True)
    embed.add_field(name="Assigned Squawk",
                    value=fp.get("assigned_transponder", "N/A"),
                    inline=True)
    embed.add_field(name="Cruise Speed",
                    value=f"{fp.get('cruise_tas', 'N/A')} kts", inline=True)
    # Row 4 — Dep Time / Enroute Time / Fuel Time
    embed.add_field(name="Dep Time", value=fp.get("deptime", "N/A"),
                    inline=True)
    embed.add_field(name="Enroute Time", value=fp.get("enroute_time", "N/A"),
                    inline=True)
    embed.add_field(name="Fuel Time", value=fp.get("fuel_time", "N/A"),
                    inline=True)

    embed.add_field(name="Route", value=fp.get("route") or "N/A", inline=False)
    embed.add_field(name="Remarks", value=fp.get("remarks") or "N/A",
                    inline=False)


# ── position field + map image ──────────────────────────────────────


async def _attach_position_and_map(embed, client_data, is_atc):
    """Add the Position field and the map image (if lat/lon available).
    Returns a discord.File for the map attachment, or None."""
    live = await _get_live_entry(client_data.get("cid"))
    if not live:
        return None

    lat = live.get("latitude")
    lon = live.get("longitude")
    if lat is None or lon is None:
        return None

    current_alt = live.get("altitude", "N/A")
    groundspeed = live.get("groundspeed", "N/A")
    heading = live.get("heading", "N/A")
    qnh = _format_qnh(live)

    # Geocoding is optional: with no OPENCAGE_KEY configured every lookup
    # returns UNKNOWN, and printing that on every embed reads as broken
    # rather than deliberate. Omit the line instead.
    location = await reverse_geocode(lat, lon)
    coords = f'{lat:.5f}, {lon:.5f}'
    telemetry = (
        f'Alt: {current_alt} ft | GS: {groundspeed} kts | HDG: {heading}°'
    )
    parts = [coords] + ([location] if location and location != UNKNOWN else []) + [telemetry]
    position_info = chr(10).join(parts)
    if qnh:
        position_info += f" | {qnh}"
    embed.add_field(name="Position", value=position_info, inline=False)

    # Pilots get the colored trail; controllers get a single pin.
    path = None
    path_altitudes = None
    map_zoom = 7
    if not is_atc:
        try:
            cid = client_data.get("cid")
            callsign = live.get("callsign")
            alt_for_trail = None if current_alt == "N/A" else current_alt
            record_position(cid, lat, lon,
                            callsign=callsign, altitude=alt_for_trail)
            track = get_track(cid)
            if len(track) >= 2:
                path = [(p[0], p[1]) for p in track]
                path_altitudes = [p[2] for p in track]
            gs_val = groundspeed if isinstance(groundspeed, (int, float)) else None
            hd_val = heading if isinstance(heading, (int, float)) else None
            map_zoom = smart_zoom_for_track(
                track, lat, lon,
                groundspeed_kts=gs_val, heading_deg=hd_val,
                fallback=7,
            )
        except Exception as e:
            print(f"[build_status_embed] track history failed: {e}")

    map_img = await generate_map_image(
        lat, lon,
        pins=[(lat, lon)],
        path_coords=path,
        path_altitudes=path_altitudes,
        zoom=map_zoom,
    )
    if map_img and not isinstance(map_img, str):
        embed.set_image(url="attachment://position_map.png")
        return discord.File(map_img, filename="position_map.png")
    return None


# ── footer ──────────────────────────────────────────────────────────


def _set_footer_from_fingerprint(embed, fingerprint):
    """Render a human-readable 'Updated: X, Y' footer when the
    fingerprint carries updated_at + updated_keys."""
    if not isinstance(fingerprint, dict):
        return
    if not fingerprint.get("updated_at"):
        return
    keys = fingerprint.get("updated_keys") or []
    readable = [_FIELD_NAMES.get(k, k) for k in keys]
    embed.set_footer(text=f"Updated: {', '.join(readable) if readable else 'no changes'}")


# ── public entry point ──────────────────────────────────────────────


async def build_status_embed(client_data, display_name, rating,
                             is_atc=False, fingerprint=None):
    callsign = client_data.get("callsign", "N/A")
    server = client_data.get("server", "N/A")
    title = (
        f"{display_name} is online as ATC" if is_atc
        else f"{display_name} is online as {fingerprint['status']}"
        if fingerprint and "status" in fingerprint
        else f"{display_name} is online"
    )

    embed = discord.Embed(
        title=title,
        color=discord.Color.green() if is_atc else discord.Color.blue(),
    )

    # Core fields shared by ATC and pilots.
    embed.add_field(name="Callsign", value=callsign, inline=True)
    embed.add_field(name="Rating", value=rating, inline=True)
    embed.add_field(name="Server", value=server, inline=True)
    embed.add_field(name="CID", value=str(client_data.get("cid", "N/A")),
                    inline=True)
    embed.add_field(name="Name", value=client_data.get("name", "N/A"),
                    inline=True)

    if is_atc:
        await _add_atc_fields(embed, client_data)
    else:
        _add_pilot_fields(embed, client_data)
        # Pilots get an aggregated transceiver-frequency line at the bottom.
        await _add_frequencies_field(embed, callsign, single_line=True,
                                     inline=False)

    file = None
    try:
        file = await _attach_position_and_map(embed, client_data, is_atc)
    except Exception as e:
        print(f"[build_status_embed] Failed to attach map: {e}")

    try:
        _set_footer_from_fingerprint(embed, fingerprint)
    except Exception as e:
        print(f"[build_status_embed] Failed to set footer: {e}")

    return embed, file
