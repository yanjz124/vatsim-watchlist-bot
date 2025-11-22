import discord
from dateutil import parser
from datetime import timezone
from utils import fetch_user_name, fetch_vatsim_data
from utils.geo import reverse_geocode
from utils.mapbox_static import generate_map_image
from config import facility


async def build_status_embed(client_data, display_name, rating, is_atc=False, fingerprint=None):
    callsign = client_data.get("callsign", "N/A")
    server = client_data.get("server", "N/A")
    title = (
        f"{display_name} is online as ATC" if is_atc
        else f"{display_name} is online as {fingerprint['status']}" if fingerprint and "status" in fingerprint
        else f"{display_name} is online"
    )

    embed = discord.Embed(
        title=title,
        color=discord.Color.green() if is_atc else discord.Color.blue()
    )

    embed.add_field(name="Callsign", value=callsign, inline=True)
    embed.add_field(name="Rating", value=rating, inline=True)
    embed.add_field(name="Server", value=server, inline=True)
    embed.add_field(name="CID", value=str(client_data.get("cid", "N/A")), inline=True)
    embed.add_field(name="Name", value=client_data.get("name", "N/A"), inline=True)

    if is_atc:
        embed.add_field(name="Frequency", value=client_data.get("frequency", "N/A"), inline=True)
        facility_id = client_data.get("facility", "N/A")
        facility_str = facility.get(facility_id, f"Unknown ({facility_id})")
        embed.add_field(name="Facility", value=facility_str, inline=True)
        embed.add_field(name="Visual Range", value=f'{client_data.get("visual_range", "N/A")} NM', inline=True)

        atis = client_data.get("text_atis", [])
        atis_text = "\n".join(atis) if atis else "N/A"
        embed.add_field(name="Text ATIS", value=atis_text, inline=False)

        try:
            logon_time = parser.isoparse(client_data.get("logon_time"))
            # Ensure UTC timezone
            if logon_time.tzinfo is None:
                logon_time = logon_time.replace(tzinfo=timezone.utc)
            else:
                logon_time = logon_time.astimezone(timezone.utc)
            logon_str = logon_time.strftime("%Y-%m-%d %H:%MZ")
            logon_timestamp = int(logon_time.timestamp())
            logon_formatted = f"{logon_str}\n<t:{logon_timestamp}:R>"
        except Exception:
            logon_formatted = client_data.get("logon_time", "N/A")

        try:
            updated_time = parser.isoparse(client_data.get("last_updated"))
            # Ensure UTC timezone
            if updated_time.tzinfo is None:
                updated_time = updated_time.replace(tzinfo=timezone.utc)
            else:
                updated_time = updated_time.astimezone(timezone.utc)
            updated_str = updated_time.strftime("%Y-%m-%d %H:%MZ")
            updated_timestamp = int(updated_time.timestamp())
            updated_formatted = f"{updated_str}\n<t:{updated_timestamp}:R>"
        except Exception:
            updated_formatted = client_data.get("last_updated", "N/A")

        embed.add_field(name="Logon Time", value=logon_formatted, inline=True)
        embed.add_field(name="Last Updated", value=updated_formatted, inline=True)

    else:
        fp = client_data.get("flight_plan")
        start_time = client_data.get("logon_time", None)
        formatted_start = "N/A"
        if start_time:
            try:
                start_dt = parser.isoparse(start_time)
                # Ensure UTC timezone
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                else:
                    start_dt = start_dt.astimezone(timezone.utc)
                start_str = start_dt.strftime("%Y-%m-%d %H:%MZ")
                start_timestamp = int(start_dt.timestamp())
                formatted_start = f"{start_str}\n<t:{start_timestamp}:R>"
            except ValueError:
                formatted_start = start_time
        embed.add_field(name="Start Time", value=formatted_start, inline=True)

        if fp:
            squawk = client_data.get("transponder", "N/A")
            assigned_squawk = fp.get("assigned_transponder", "N/A")
            # Aircraft display logic: aircraft_short > aircraft_faa > aircraft
            aircraft = fp.get("aircraft_short")
            if not aircraft:
                aircraft = fp.get("aircraft_faa")
            if not aircraft:
                aircraft = fp.get("aircraft", "N/A")
            flight_rules = f"{fp.get('flight_rules', 'N/A')}FR"
            dep = fp.get("departure", "N/A")
            arr = fp.get("arrival", "N/A")
            alternate = fp.get("alternate", "N/A")
            alt = fp.get("altitude", "N/A")
            cruise_tas = fp.get("cruise_tas", "N/A")
            deptime = fp.get("deptime", "N/A")
            enroute_time = fp.get("enroute_time", "N/A")
            fuel_time = fp.get("fuel_time", "N/A")
            route = fp.get("route", "N/A") or "N/A"
            
            embed.add_field(name="Aircraft", value=aircraft, inline=True)
            embed.add_field(name="Flight Type", value=flight_rules, inline=True)
            embed.add_field(name="Altitude", value=alt, inline=True)
            # Departure, Arrival, Alternate
            embed.add_field(name="Departure", value=dep, inline=True)
            embed.add_field(name="Arrival", value=arr, inline=True)
            embed.add_field(name="Alternate", value=alternate, inline=True)
            # Current Squawk, Assigned Squawk, Cruise Speed
            embed.add_field(name="Current Squawk", value=squawk, inline=True)
            embed.add_field(name="Assigned Squawk", value=assigned_squawk, inline=True)
            embed.add_field(name="Cruise Speed", value=f"{cruise_tas} kts", inline=True)
            # Dep Time, Enroute Time, Fuel Time
            embed.add_field(name="Dep Time", value=deptime, inline=True)
            embed.add_field(name="Enroute Time", value=enroute_time, inline=True)
            embed.add_field(name="Fuel Time", value=fuel_time, inline=True)
            embed.add_field(name="Route", value=route, inline=False)
            remarks = fp.get("remarks", "N/A") or "N/A"
            embed.add_field(name="Remarks", value=remarks, inline=False)
        else:
            embed.add_field(name="Flight Plan", value="No flight plan filed", inline=False)

    # Initialize file variable
    file = None

    # 🗺 Add map if lat/lon exists
    try:
        vatsim_data = await fetch_vatsim_data()
        if isinstance(vatsim_data, dict):
            all_clients = vatsim_data.get("controllers", []) + vatsim_data.get("pilots", [])
            live_entry = next((x for x in all_clients if x.get("cid") == client_data.get("cid")), None)
        else:
            live_entry = None

        if live_entry:
            lat = live_entry.get("latitude")
            lon = live_entry.get("longitude")
            current_alt = live_entry.get("altitude", "N/A")
            groundspeed = live_entry.get("groundspeed", "N/A")
            heading = live_entry.get("heading", "N/A")
            
            # QNH values
            qnh_inhg = live_entry.get("qnh_i_hg", "N/A")
            qnh_mb = live_entry.get("qnh_mb", "N/A")
            if qnh_inhg != "N/A" and qnh_mb != "N/A":
                qnh_display = f"QNH: {qnh_inhg} inHg / {qnh_mb} hPa"
            elif qnh_inhg != "N/A":
                qnh_display = f"QNH: {qnh_inhg} inHg"
            elif qnh_mb != "N/A":
                qnh_display = f"QNH: {qnh_mb} hPa"
            else:
                qnh_display = ""
            
            if lat is not None and lon is not None:
                location = await reverse_geocode(lat, lon)
                position_info = (
                    f"{lat:.5f}, {lon:.5f}\n{location}\n"
                    f"Alt: {current_alt} ft | GS: {groundspeed} kts | HDG: {heading}°"
                )
                if qnh_display:
                    position_info += f" | {qnh_display}"
                embed.add_field(name="Position", value=position_info, inline=False)

                map_img = await generate_map_image(lat, lon, pins=[(lat, lon)], zoom=7)
                if map_img:
                    file = discord.File(map_img, filename="position_map.png")
                    embed.set_image(url="attachment://position_map.png")

    except Exception as e:
        print(f"[build_status_embed] Failed to attach map: {e}")

    # Footer: Last updated and what changed, if provided
    try:
        if isinstance(fingerprint, dict):
            updated_at = fingerprint.get("updated_at")
            updated_keys = fingerprint.get("updated_keys") or []
            if updated_at:
                # Human-readable field name mapping
                field_names = {
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
                readable_keys = [field_names.get(k, k) for k in updated_keys]
                what = ", ".join(readable_keys) if readable_keys else "no changes"
                footer_text = f"Updated: {what}"
                embed.set_footer(text=footer_text)
    except Exception as e:
        print(f"[build_status_embed] Failed to set footer: {e}")

    return embed, file