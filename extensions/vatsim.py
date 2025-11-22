# extensions/vatsim.py

from datetime import datetime

import aiohttp
import discord
import requests
import asyncio
import re
from dateutil import parser
from datetime import timezone
from typing import Optional
from discord.ext import commands
from discord.utils import utcnow
from utils import generate_map_image
from utils import fetch_vatsim_data, build_status_embed, format_date, format_time
from config import ROLE_ID, atc_rating, pilot_rating, military_rating, facility, VATUSA_API_KEY
from utils.vatsim_datafeed import fetch_transceivers_data, get_frequencies_for_callsign

vatsim_url = 'https://data.vatsim.net/v3/vatsim-data.json'


# def format_date(iso_string):
#     if not iso_string:
#         return "N/A"
#     try:
#         return datetime.fromisoformat(iso_string.replace("Z", "+00:00")).strftime("%b %d, %Y")
#     except Exception:
#         return iso_string  # fallback
#
#
# def format_time(iso_str):
#     try:
#         return parser.isoparse(iso_str).strftime("%Y-%m-%d %H:%MZ")
#     except Exception:
#         return iso_str or "N/A"


async def fetch_user_name(cid, session=None):
    if cid in ('N/A', 0, None):
        return 'N/A'

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        url = f"https://api.vatusa.net/v2/user/{cid}"
        timeout = aiohttp.ClientTimeout(total=20)
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


def determine_flight_category(metar: str) -> str:
    # Check for CAVOK
    if "CAVOK" in metar:
        return "VFR"

    # Visibility (defaults to high in case it's not found)
    visibility = 999  # Statute miles or meters depending on format

    sm_match = re.search(r"(\d{1,2})SM", metar)
    m_match = re.search(r"\b(\d{4})\b", metar)  # ICAO meters
    if sm_match:
        visibility = int(sm_match.group(1))
    elif m_match:
        visibility = int(m_match.group(1)) / 1609.34  # meters to miles

    # Ceiling
    ceiling_match = re.findall(r"(FEW|SCT|BKN|OVC)(\d{3})", metar)
    ceiling_ft = 99999
    for layer in ceiling_match:
        cover, height_hundreds = layer
        if cover in ("BKN", "OVC"):
            ceiling_ft = min(ceiling_ft, int(height_hundreds) * 100)

    # Category logic
    if ceiling_ft >= 3000 and visibility >= 5:
        return "VFR"
    elif ceiling_ft >= 1000 and visibility >= 3:
        return "MVFR"
    elif ceiling_ft >= 500 and visibility >= 1:
        return "IFR"
    elif ceiling_ft < 500 or visibility < 1:
        return "LIFR"

    return "Unknown"


class Vatsim(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def fetch_facility_details(self, session, facility_id):
        url = f"https://api.vatusa.net/v2/facility/{facility_id}"
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                return None

    @commands.command()
    async def cid(self, ctx, cid: int):
        """Get VATSIM user info by CID"""
        url = f"https://api.vatsim.net/api/ratings/{cid}/"
        response = requests.get(url)
        print(f"API response: {response.status_code}")

        if response.status_code != 200:
            await ctx.send("Error: CID not found or API request failed.")
            return

        data = response.json()
        print(f"API data: {data}")

        embed = discord.Embed(title=f"Information for CID: {cid}", color=discord.Color.orange())
        field_count = 0

        def get_field_name(key):
            mapping = {
                "id": "CID",
                "rating": "Controller Rating",
                "pilotrating": "Pilot Rating",
                "militaryrating": "Military Rating",
                "reg_date": "Reg Date",
                "susp_date": "Susp Date",
                "region": "Region",
                "division": "Division",
                "subdivision": "Subdivision",
                "lastratingchange": "Last Rating Change"
            }
            return mapping.get(key, key.replace('_', ' ').title())

        def get_field_value(key, value):
            # Add Discord relative timestamp for reg_date, susp_date, and lastratingchange
            if key in ("reg_date", "susp_date", "lastratingchange") and value:
                try:
                    dt = parser.isoparse(value)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    zulu_str = dt.strftime("%Y-%m-%d %H:%MZ")
                    discord_ts = int(dt.timestamp())
                    return f"{zulu_str}\n<t:{discord_ts}:R>"
                except Exception:
                    return str(value)
            if key == "rating":
                return atc_rating.get(int(value), str(value))
            if key == "pilotrating":
                return pilot_rating.get(int(value), str(value))
            if key == "militaryrating":
                return military_rating.get(int(value), str(value))
            if key == "facility":
                return facility.get(int(value), str(value))
            return str(value)

        for key, value in data.items():
            if field_count >= 25:
                break
            if value is None:
                continue

            field_name = get_field_name(key)
            field_value = get_field_value(key, value)

            embed.add_field(name=field_name, value=field_value, inline=False)
            field_count += 1

        if field_count >= 25:
            embed.add_field(
                name="Notice",
                value="Not all data could be displayed due to Discord's embed field limits.",
                inline=False,
            )

        await ctx.send(embed=embed)

        # Now try VATUSA
        vatusa_url = f"https://api.vatusa.net/user/{cid}?apikey={VATUSA_API_KEY}"
        vatusa_response = requests.get(vatusa_url)

        try:
            vatusa_data = vatusa_response.json()
            if vatusa_data.get("data", {}).get("status") == "error":
                return  # Don't show anything if not found
        except Exception:
            return

        # Reuse your usa command logic, or create a helper function for the embed
        await self.usa(ctx, cid)

    @commands.command()
    async def usa(self, ctx, cid: int):
        """Get VATUSA user info by CID"""
        # 'cid' is already an int from the command signature
        url = f"https://api.vatusa.net/user/{cid}?apikey={VATUSA_API_KEY}"

        response = requests.get(url)
        if response.status_code != 200:
            await ctx.send("Failed to retrieve data from VATUSA API.")
            return

        data = response.json().get("data", {})

        def format_date(date_str):
            if not date_str:
                return "N/A"
            try:
                dt = parser.parse(date_str)
                return dt.strftime("%b %d, %Y")
            except:
                return date_str

        def format_bool(val):
            return str(val) if val is not None else "N/A"

        # Main Embed
        name = f"{data.get('fname', '')} {data.get('lname', '')}".strip()
        embed = discord.Embed(title=f"{name} | CID: {cid}", color=discord.Color.teal())

        fields = {
            "CID": cid,
            "Name": name,
            "Email": data.get("email", "N/A"),
            "Facility": data.get("facility", "N/A"),
            "Rating": data.get("rating_short", "N/A"),
            "Created At": format_date(data.get("created_at")),
            "Updated At": format_date(data.get("updated_at")),
            "Flag Needbasic": format_bool(data.get("flag_needbasic")),
            "Flag Xferoverride": format_bool(data.get("flag_xferOverride")),
            "Facility Join": format_date(data.get("facility_join")),
            "Flag BroadcastoptedIn": format_bool(data.get("flag_broadcastOptedIn")),
            "Flag PreventstaffAssign": format_bool(data.get("flag_preventStaffAssign")),
            "Last Activity": format_date(data.get("lastactivity")),
            "Discord ID": f"<@{data.get('discord_id')}>" if data.get("discord_id") else "N/A",
            "Last Cert Sync": format_date(data.get("last_cert_sync")),
            "Flag Nameprivacy": format_bool(data.get("flag_nameprivacy")),
            "Last Competency Date": format_date(data.get("last_competency_date")),
            "Promotion Eligible": format_bool(data.get("promotion_eligible")),
            "Transfer Eligible": format_bool(data.get("transfer_eligible")),
            "Is Mentor": format_bool(data.get("isMentor")),
            "Is Sup/Ins": format_bool(data.get("isSupIns")),
            "Last Promotion": format_date(data.get("last_promotion")),
        }

        for i, (k, v) in enumerate(fields.items()):
            embed.add_field(name=k, value=v, inline=True)

        await ctx.send(embed=embed)

        # Second Embed - Roles and Visiting Facilities
        roles = data.get("roles", [])
        visits = data.get("visiting_facilities", [])
        roles_str = "N/A"
        visits_str = "N/A"

        if roles:
            role_lines = []
            for role in roles:
                role_lines.append(
                    f"Facility: {role.get('facility', 'N/A')}; "
                    f"Role: {role.get('role', 'N/A')}; "
                    f"Created At: {format_date(role.get('created_at'))}"
                )
            roles_str = "\n".join(role_lines)

        if visits:
            visit_lines = []
            for visit in visits:
                visit_lines.append(
                    f"Facility: {visit.get('facility', 'N/A')}; "
                    f"Created At: {format_date(visit.get('created_at'))}; "
                    f"Updated At: {format_date(visit.get('updated_at'))}"
                )
            visits_str = "\n".join(visit_lines)

        embed2 = discord.Embed(title=f"Additional Info for CID: {cid}", color=discord.Color.dark_blue())
        embed2.add_field(name="Roles", value=roles_str, inline=True)
        embed2.add_field(name="Visiting Facilities", value=visits_str, inline=True)

        await ctx.send(embed=embed2)

    @commands.command()
    async def lname(self, ctx, lastname: str, page: int = 1):
        """Search VATSIM users by last name"""
        author_id = ctx.author.id
        users_per_page = 25
        url = f"https://api.vatusa.net/v2/user/filterlname/{lastname}"

        if len(lastname) < 4:
            await ctx.send("Please provide at least **4 letters** for partial last name search.")
            return

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    text = await response.text()
                    await ctx.send(f"Error: {response.status} - {text}")
                    return

                data = await response.json()
                users = data.get('data', [])

                if not users:
                    await ctx.send("No users found with that last name.")
                    return

                if page:
                    total_pages = (len(users) + users_per_page - 1) // users_per_page
                    page = max(1, min(page, total_pages))
                    start, end = (page - 1) * users_per_page, page * users_per_page
                    paged_users = users[start:end]

                    embed = discord.Embed(
                        title=f"Users with last name: {lastname} (Page {page}/{total_pages})",
                        color=discord.Color.green()
                    )
                    for user in paged_users:
                        full_name = f"{user['fname']} {user['lname']}"
                        embed.add_field(name=full_name, value=f"CID: {user['cid']}", inline=False)
                    await ctx.send(embed=embed)

                else:
                    chunks = [users[i:i + users_per_page] for i in range(0, len(users), users_per_page)]
                    for i, chunk in enumerate(chunks):
                        embed = discord.Embed(
                            title=f"Users with last name: {lastname} (Page {i + 1}/{len(chunks)})",
                            color=discord.Color.green()
                        )
                        for user in chunk:
                            full_name = f"{user['fname']} {user['lname']}"
                            embed.add_field(name=full_name, value=f"CID: {user['cid']}", inline=False)
                        await ctx.send(embed=embed)
    @commands.command()
    async def atis(self, ctx, icao: str):
        """Get ATIS for an airport"""
        response = requests.get(vatsim_url)
        data = response.json()
        airport_code = icao.upper()

        found_atis = [
            atis for atis in data.get("atis", [])
            if atis.get("callsign", "").startswith(airport_code)
        ]

        if not found_atis:
            await ctx.send(f"No ATIS found for {airport_code}.")
            return

        for atis_entry in found_atis:
            callsign = atis_entry.get("callsign", "N/A")
            frequency = atis_entry.get("frequency", "N/A")
            code = atis_entry.get("atis_code", "N/A")
            text_atis = "\n".join(atis_entry.get("text_atis", []))

            embed = discord.Embed(
                title=f"{callsign} ({code})",
                description=text_atis,
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Freq: {frequency}")
            await ctx.send(embed=embed)

    @commands.command()
    async def sup(self, ctx):
        """List online VATSIM supervisors"""

        try:
            data = await fetch_vatsim_data()
        except Exception as e:
            await ctx.send("Failed to fetch VATSIM data.")
            print(f"Error in sup command: {e}")
            return

        if not isinstance(data, dict):
            await ctx.send("Failed to fetch VATSIM data.")
            return

        supervisors = []

        for controller in data.get("controllers", []):
            if controller["callsign"].endswith("_SUP"):
                cid = controller["cid"]
                name = controller.get("name", f"CID {cid}")  # fallback name from datafeed

                # Try to get real name from VATUSA
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f"https://api.vatusa.net/v2/user/{cid}") as resp:
                            if resp.status == 200:
                                user_data = await resp.json()
                                fname = user_data["data"].get("fname")
                                lname = user_data["data"].get("lname")
                                if fname and lname:
                                    name = f"{fname} {lname}"
                except Exception as e:
                    print(f"Failed to fetch VATUSA name for {cid}: {e}")

                supervisors.append(f"{controller['callsign']} — {name} ({cid})")

        if supervisors:
            embed = discord.Embed(title="Online Supervisors", description="\n".join(supervisors), color=0x00FF00)
        else:
            embed = discord.Embed(title="No Supervisors Online", description="Off Duty", color=0xFF0000)

        await ctx.send(embed=embed)

    @commands.command()
    async def status(self, ctx, cid: int):
        """Check online status of a VATSIM user"""
        datafeed_url = "https://data.vatsim.net/v3/vatsim-data.json"

        async with aiohttp.ClientSession() as session:
            async with session.get(datafeed_url) as response:
                if response.status != 200:
                    await ctx.send("Failed to fetch VATSIM datafeed.")
                    return

                feed = await response.json()
                pilots = feed.get("pilots", [])
                atcs = feed.get("controllers", [])

                # Try to find the user as ATC first
                client_data = next((c for c in atcs if c.get("cid") == cid), None)
                is_atc = True

                if not client_data:
                    # Try to find as pilot
                    client_data = next((p for p in pilots if p.get("cid") == cid), None)
                    is_atc = False

                if not client_data:
                    embed = discord.Embed(
                        title=f"CID {cid} is Offline",
                        description="The user is not currently connected to the VATSIM network.",
                        color=discord.Color.red()
                    )
                    await ctx.send(embed=embed)
                    return

                # Build display name and rating
                display_name = f"CID {cid}"
                rating_id = client_data.get("rating") if is_atc else client_data.get("pilot_rating", -1)

                rating_map = atc_rating if is_atc else pilot_rating
                rating_str = rating_map.get(rating_id, f"Unknown ({rating_id})")
                status_label = "ATC" if is_atc else "Pilot"

                fingerprint = {"status": status_label}

                embed, file = await build_status_embed(
                    client_data=client_data,
                    display_name=display_name,
                    rating=rating_str,
                    is_atc=is_atc,
                    fingerprint=fingerprint
                )

                if file:
                    await ctx.send(embed=embed, file=file)
                else:
                    await ctx.send(embed=embed)

    @commands.command()
    async def stats(self, ctx, cid: int):
        """Get VATSIM statistics for a user"""
        url = f"https://api.vatsim.net/v2/members/{cid}/stats"
        response = requests.get(url)

        if response.status_code != 200:
            await ctx.send(f"Error retrieving stats for CID {cid}.")
            return

        data = response.json()

        # Get real name from VATUSA API
        real_name = "N/A"
        try:
            usa_resp = requests.get(f"https://api.vatusa.net/user/{cid}")
            if usa_resp.status_code == 200:
                usa_data = usa_resp.json().get("data", {})
                real_name = f"{usa_data.get('fname', '')} {usa_data.get('lname', '')}".strip()
        except Exception:
            pass

        embed = discord.Embed(
            title=f"Statistics for CID: {cid}",
            color=discord.Color.green()
        )

        # Header
        embed.add_field(name="CID", value=str(cid), inline=True)
        embed.add_field(name="Real Name", value=real_name, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        # ATC and PILOT
        embed.add_field(name="ATC Hours", value=str(data.get("atc", 0.0)), inline=True)
        embed.add_field(name="Pilot Hours", value=str(data.get("pilot", 0.0)), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        left = ['s1', 's2', 's3', 'c1', 'c2', 'c3']
        right = ['i1', 'i2', 'i3', 'sup', 'adm']

        def format_column(keys):
            return "\n".join(f"{key.upper()}: {data.get(key, 0.0)}" for key in keys)

        embed.add_field(name="Controller Hours", value=format_column(left), inline=True)
        embed.add_field(name="\u200b", value=format_column(right), inline=True)

        await ctx.send(embed=embed)

    @commands.command(name="callsign")
    async def callsign_lookup(self, ctx, callsign: str):
        """Look up a VATSIM callsign with location. Usage: !callsign <callsign>"""
        callsign = callsign.upper()

        try:
            data = await fetch_vatsim_data()
            if not isinstance(data, dict):
                await ctx.send("Failed to fetch VATSIM data.")
                return

            # Search in each group individually
            match = next(
                (client for client in data.get("pilots", []) if client.get("callsign") == callsign),
                None
            )
            source = "pilot"

            if not match:
                match = next(
                    (client for client in data.get("controllers", []) if client.get("callsign") == callsign),
                    None
                )
                source = "controller"

            if not match:
                match = next(
                    (client for client in data.get("atis", []) if client.get("callsign") == callsign),
                    None
                )
                source = "atis"

            if not match:
                await ctx.send(f"Callsign `{callsign}` is not currently connected to the VATSIM network.")
                return

            is_atc = source in ("controller", "atis")
            rating_id = match.get("rating") if is_atc else match.get("pilot_rating", -1)
            rating_map = atc_rating if is_atc else pilot_rating
            rating_str = rating_map.get(rating_id, f"Unknown ({rating_id})")

            fingerprint = {"status": source.upper()}
            display_name = callsign

            embed, file = await build_status_embed(
                client_data=match,
                display_name=display_name,
                rating=rating_str,
                is_atc=is_atc,
                fingerprint=fingerprint
            )

            if file:
                await ctx.send(embed=embed, file=file)
            else:
                await ctx.send(embed=embed)

        except Exception as e:
            print(f"Error in !callsign: {e}")
            await ctx.send("Failed to fetch callsign data.")

    @commands.command(name="com")
    async def get_com_frequencies(self, ctx, callsign: Optional[str] = None):
        """Get frequencies for a VATSIM callsign. Usage: !com <callsign>"""
        if not callsign:
            await ctx.send("Usage: `!com [Callsign]`")
            return

        try:
            data = fetch_transceivers_data()
            frequencies = get_frequencies_for_callsign(callsign.upper(), data)

            if frequencies:
                freq_text = ", ".join(frequencies)
                embed = discord.Embed(title=f"Callsign: {callsign.upper()}", color=discord.Color.blue())
                embed.add_field(name="Frequencies", value=freq_text, inline=False)
            else:
                embed = discord.Embed(title="Error", description=f"No frequencies found for {callsign.upper()}",
                                      color=discord.Color.red())

            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"Error fetching data: {e}")

    @commands.command()
    async def faclist(self, ctx):
        """Get list of all VATUSA facilities"""
        async with aiohttp.ClientSession() as session:
            url = "https://api.vatusa.net/v2/facility/"
            async with session.get(url) as response:
                if response.status != 200:
                    text = await response.text()
                    await ctx.send(f"Error retrieving facilities: {response.status} - {text}")
                    return

                data = await response.json()
                facilities = data.get('data', [])
                if not facilities:
                    await ctx.send("No facilities data available.")
                    return

                status_msg = await ctx.send("Fetching facility staff… please wait")
                embed = discord.Embed(
                    title="List of VATUSA Facilities",
                    color=discord.Color.blue(),
                    description="Here are the facilities registered under VATUSA:"
                )

                embeds = []
                count = 0
                completed = 0
                total = len(facilities)

                for facility in facilities:
                    if count >= 25:
                        embeds.append(embed)
                        embed = discord.Embed(
                            title="List of VATUSA Facilities (Continued)",
                            color=discord.Color.blue()
                        )
                        count = 0

                    name = facility.get('name', 'N/A')
                    fac_url = facility.get('url', 'No URL provided')
                    atm_cid = facility.get('atm')
                    datm_cid = facility.get('datm')
                    ta_cid = facility.get('ta')
                    ec_cid = facility.get('ec')
                    fe_cid = facility.get('fe')
                    wm_cid = facility.get('wm')

                    # Fetch names in parallel
                    atm_name, datm_name, ta_name, ec_name, fe_name, wm_name = await asyncio.gather(
                        fetch_user_name(atm_cid, session),
                        fetch_user_name(datm_cid, session),
                        fetch_user_name(ta_cid, session),
                        fetch_user_name(ec_cid, session),
                        fetch_user_name(fe_cid, session),
                        fetch_user_name(wm_cid, session)
                    )

                    details = (
                        f"URL: {fac_url}\n"
                        f"ATM: {atm_name} (CID: {atm_cid})\n"
                        f"DATM: {datm_name} (CID: {datm_cid})\n"
                        f"TA: {ta_name} (CID: {ta_cid})\n"
                        f"EC: {ec_name} (CID: {ec_cid})\n"
                        f"FE: {fe_name} (CID: {fe_cid})\n"
                        f"WM: {wm_name} (CID: {wm_cid})\n"
                        f"Active: {'Yes' if facility.get('active', 0) == 1 else 'No'}\n"
                        f"ACE: {'Yes' if facility.get('ace', 0) == 1 else 'No'}"
                    )
                    embed.add_field(name=f"{facility['id']} - {name}", value=details, inline=False)
                    count += 1
                    completed += 1

                    # Update loading message every 3 facilities
                    if completed % 3 == 0 or completed == total:
                        await status_msg.edit(content=f"Loading… {completed}/{total} facilities")

                embeds.append(embed)  # append final batch

                await status_msg.delete()
                for emb in embeds:
                    await ctx.send(embed=emb)

    @commands.command()
    async def facinfo(self, ctx, facility_id: str):
        """Get info for a VATUSA facility (e.g. ZDC)"""
        if not facility_id:
            await ctx.send("Usage: `!facinfo [FACILITY_ID]`\nExample: `!facinfo ZDC`")
            return

        facility_id = facility_id.upper()
        status_msg = await ctx.send(f"Fetching info for {facility_id}…")

        async with aiohttp.ClientSession() as session:
            url = f"https://api.vatusa.net/v2/facility/{facility_id}"
            async with session.get(url) as response:
                if response.status != 200:
                    await status_msg.edit(content=f"Failed to retrieve data for facility {facility_id}.")
                    return
                data = await response.json()

            if "data" not in data or "facility" not in data["data"]:
                await status_msg.edit(content=f"No data available for facility {facility_id}.")
                return

            info = data["data"]["facility"]["info"]
            roles = data["data"]["facility"]["roles"]

            embed = discord.Embed(
                title=f"Details for {facility_id} - {info.get('name', 'Unknown')}",
                color=discord.Color.blue()
            )
            embed.add_field(name="URL", value=info.get('url', 'N/A'), inline=False)
            embed.add_field(name="Region", value=str(info.get('region', 'N/A')), inline=True)
            embed.add_field(name="Active", value='Yes' if info.get('active', 0) == 1 else 'No', inline=True)
            embed.add_field(name="ACE", value='Yes' if info.get('ace', 0) == 1 else 'No', inline=True)

            embeds = [embed]
            field_count = len(embed.fields)

            # Prepare role data
            total_roles = len(roles)
            cids = [r["cid"] for r in roles]
            role_names = [r.get("role", "Unknown") for r in roles]
            created_dates = [r.get("created_at", "")[:10] for r in roles]

            # Resolve names in parallel
            names = await asyncio.gather(*[fetch_user_name(cid, session) for cid in cids])

            for i, (cid, role_name, created, name) in enumerate(zip(cids, role_names, created_dates, names), start=1):
                role_display = f"{role_name} (CID: {cid})"
                value = f"Name: {name}\nSince: {created}"

                if field_count >= 25:
                    embed = discord.Embed(title=f"More Roles for {facility_id}", color=discord.Color.blue())
                    embeds.append(embed)
                    field_count = 0

                embed.add_field(name=role_display, value=value, inline=False)
                field_count += 1

                # Update progress
                if i % 5 == 0 or i == total_roles:
                    await status_msg.edit(content=f"Resolving staff… {i}/{total_roles} complete")

            await status_msg.delete()
            for emb in embeds:
                await ctx.send(embed=emb)

    @commands.command()
    async def facroster(self, ctx, *args):
        """Get VATUSA facility roster. Usage: !facroster <facility_id> [home/visit/both]"""
        if len(args) == 0:
            await ctx.send("Usage: `!facroster [FACILITY_ID] [home/visit/both]`\nExample: `!facroster ZDC home`")
            return

        facility_id = args[0].upper()
        roster_type = args[1].lower() if len(args) > 1 else "home"

        if roster_type not in ["home", "visit", "both"]:
            await ctx.send("Usage: `!facroster [FACILITY_ID] [home/visit/both]`")
            return

        status_msg = await ctx.send(f"Fetching {roster_type} roster for {facility_id}…")

        async with aiohttp.ClientSession() as session:
            url = f"https://api.vatusa.net/v2/facility/{facility_id}/roster/{roster_type}"
            async with session.get(url) as response:
                if response.status != 200:
                    await status_msg.edit(content=f"Failed to retrieve roster for {facility_id}.")
                    return

                result = await response.json()
                roster = result.get("data", [])
                if not roster:
                    await status_msg.edit(content=f"No data available for {facility_id} ({roster_type}).")
                    return

                embeds = []
                total = len(roster)

                for i, person in enumerate(roster, start=1):
                    cid = person['cid']
                    name_privacy = person.get("flag_nameprivacy", False)

                    if name_privacy:
                        name = await fetch_user_name(cid, session)
                    else:
                        name = f"{person['fname']} {person['lname']}"

                    email = person.get("email", "N/A")
                    rating = person.get("rating_short", "N/A")
                    last_active_raw = person.get("lastactivity")
                    last_active = format_time(last_active_raw) if last_active_raw else "N/A"

                    details = (
                        f"Rating: {rating}\n"
                        f"Email: {email}\n"
                        f"Last Activity: {last_active}"
                    )

                    if not embeds or len(embeds[-1].fields) >= 25:
                        embeds.append(discord.Embed(
                            title=f"{facility_id} Roster - {roster_type.capitalize()} ({total} controllers)",
                            color=discord.Color.green()
                        ))

                    embeds[-1].add_field(
                        name=f"{name} (CID: {cid})",
                        value=details,
                        inline=False
                    )

                    if i % 5 == 0 or i == total:
                        await status_msg.edit(content=f"Processed {i}/{total} controllers…")

        await status_msg.delete()
        for embed in embeds:
            await ctx.send(embed=embed)

    @commands.command()
    async def metar(self, ctx, icao: str):
        """Get METAR for an airport"""
        icao = icao.upper()

        url = f"https://metar.vatsim.net/{icao}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return await ctx.send("Could not retrieve METAR.")

                metar = (await resp.text()).strip()

        if not metar or metar.lower().startswith("error") or "no metar" in metar.lower():
            color = discord.Color.greyple()
            category = "Unknown"
            metar_text = "METAR not available."
        else:
            category = determine_flight_category(metar)
            color = {
                "VFR": discord.Color.green(),
                "MVFR": discord.Color.blue(),
                "IFR": discord.Color.red(),
                "LIFR": discord.Color.purple(),
            }.get(category, discord.Color.greyple())
            metar_text = metar

        embed = discord.Embed(
            title=f"{icao} METAR",
            description=metar_text,
            color=color,
            timestamp=utcnow()
        )
        #  embed.add_field(name="Flight Category", value=category, inline=False)

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Vatsim(bot))
