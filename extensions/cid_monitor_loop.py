# extensions/cid_monitor_loop.py

import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime
from dateutil import parser
from collections import defaultdict
from utils import get_cid_to_monitor, fetch_vatsim_data, build_status_embed, fetch_user_name
from config import atc_rating, pilot_rating, CHANNEL_ID, facility
import time

class VATSIMMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.status_cache = {}  # cid -> list of fingerprints
        self.message_cache = {}  # cid -> discord.Message
        self.last_map_refresh = {}  # cid -> epoch seconds of last map update
        self.monitor_loop.start()

    async def cog_unload(self):
        self.monitor_loop.cancel()

    @tasks.loop(seconds=15)
    async def monitor_loop(self):
        cid_map = get_cid_to_monitor()

        try:
            data = await fetch_vatsim_data()
            if not isinstance(data, dict):
                return
            pilots = data.get("pilots", [])
            controllers = data.get("controllers", [])
            # ATIS is ignored
        except Exception as e:
            print(f"Error fetching VATSIM data: {e}")
            return

        found_cids = defaultdict(list)

        for client in pilots:
            client["_source"] = "pilot"
            found_cids[int(client["cid"])].append(client)

        for client in controllers:
            client["_source"] = "controller"
            found_cids[int(client["cid"])].append(client)

        for cid, name in cid_map.items():
            connections = found_cids.get(cid, [])
            new_fp_list = []


            if connections:
                client_data = connections[0]  # Only show the first connection for this CID
                callsign = client_data.get("callsign", "N/A")
                source = client_data.get("_source", "unknown")
                is_atc = (source == "controller")
                rating_id = client_data.get("rating") if is_atc else client_data.get("pilot_rating", -1)
                rating = (atc_rating if is_atc else pilot_rating).get(rating_id, f"Unknown ({rating_id})")
                server = client_data.get("server", "N/A")
                start_time = client_data.get("logon_time")

                # Build a richer fingerprint so message edits reflect meaningful updates
                if is_atc:
                    atis_list = client_data.get("text_atis", []) or []
                    base_fp = {
                        "status": source,
                        "callsign": callsign,
                        "rating": rating,
                        "server": server,
                        "start_time": start_time,
                        "frequency": client_data.get("frequency"),
                        "facility": client_data.get("facility"),
                        "visual_range": client_data.get("visual_range"),
                        "text_atis": "\n".join(atis_list),
                        "last_updated": client_data.get("last_updated"),
                        "atis_code": client_data.get("atis_code"),
                    }
                else:
                    fp = client_data.get("flight_plan") or {}
                    aircraft = fp.get("aircraft_short") or fp.get("aircraft_faa") or fp.get("aircraft")
                    base_fp = {
                        "status": source,
                        "callsign": callsign,
                        "rating": rating,
                        "server": server,
                        "start_time": start_time,
                        # Pilot dynamic and FP details
                        "transponder": client_data.get("transponder"),
                        "assigned_transponder": fp.get("assigned_transponder"),
                        "aircraft": aircraft,
                        "flight_rules": fp.get("flight_rules"),
                        "departure": fp.get("departure"),
                        "arrival": fp.get("arrival"),
                        "alternate": fp.get("alternate"),
                        "cruise_tas": fp.get("cruise_tas"),
                        "altitude": fp.get("altitude"),
                        "deptime": fp.get("deptime"),
                        "enroute_time": fp.get("enroute_time"),
                        "fuel_time": fp.get("fuel_time"),
                        "route": fp.get("route"),
                        "remarks": fp.get("remarks"),
                    }

                # Determine what changed vs. previous cached fingerprint (exclude meta)
                old_fp_list = self.status_cache.get(cid, [])
                old_fp = old_fp_list[0] if old_fp_list else None
                now_epoch = int(time.time())
                if not old_fp:
                    changed_keys = ["initial"]
                else:
                    changed_keys = sorted([k for k in base_fp.keys() if base_fp.get(k) != old_fp.get(k)])
                # Create a display fingerprint including update metadata for the embed footer
                fingerprint = dict(base_fp)
                fingerprint["updated_keys"] = changed_keys
                fingerprint["updated_at"] = now_epoch
                new_fp_list.append(base_fp)

                channel = self.bot.get_channel(CHANNEL_ID)
                # If new connection (not in cache), send a new message
                if not old_fp_list:
                    embed, file = await build_status_embed(
                        client_data=client_data,
                        display_name=name,
                        rating=rating,
                        is_atc=is_atc,
                        fingerprint=fingerprint
                    )
                    if channel:
                        try:
                            if file:
                                sent = await channel.send(embed=embed, file=file)
                            else:
                                sent = await channel.send(embed=embed)
                            self.message_cache[cid] = sent
                            self.last_map_refresh[cid] = time.time()
                        except Exception as e:
                            print(f"Error sending new message for CID {cid}: {e}")
                # If fingerprint changed but still same connection, edit the message
                elif base_fp != old_fp_list[0]:
                    embed, file = await build_status_embed(
                        client_data=client_data,
                        display_name=name,
                        rating=rating,
                        is_atc=is_atc,
                        fingerprint=fingerprint
                    )
                    last_msg = self.message_cache.get(cid)
                    if channel and last_msg:
                        try:
                            if file:
                                await last_msg.edit(embed=embed, attachments=[file])
                            else:
                                await last_msg.edit(embed=embed, attachments=[])
                            self.last_map_refresh[cid] = time.time()
                        except Exception as e:
                            print(f"Error editing message for CID {cid}: {e}")

                # Periodic position/map refresh without fingerprint changes
                refresh_interval = 600 if is_atc else 300  # ATC: 10min, Pilot: 5min
                last_refresh = self.last_map_refresh.get(cid, 0)
                now = time.time()
                if now - last_refresh >= refresh_interval:
                    last_msg = self.message_cache.get(cid)
                    if channel and last_msg:
                        try:
                            # For periodic refresh, annotate update meta without changing cached fp
                            refresh_fp = dict(self.status_cache.get(cid, [base_fp])[0])
                            refresh_fp["updated_keys"] = ["position"]
                            refresh_fp["updated_at"] = int(now)
                            embed, file = await build_status_embed(
                                client_data=client_data,
                                display_name=name,
                                rating=rating,
                                is_atc=is_atc,
                                fingerprint=refresh_fp
                            )
                            if file:
                                await last_msg.edit(embed=embed, attachments=[file])
                            else:
                                await last_msg.edit(embed=embed, attachments=[])
                            self.last_map_refresh[cid] = now
                        except Exception as e:
                            print(f"Error refreshing map for CID {cid}: {e}")


            # If no connections and previously online, send a new offline message
            if not connections and self.status_cache.get(cid):
                embed = discord.Embed(
                    title=f"{name} went offline",
                    description=f"CID {cid} is no longer connected to the network.",
                    color=discord.Color.red()
                )
                channel = self.bot.get_channel(CHANNEL_ID)
                if channel:
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        print(f"Error sending offline message for CID {cid}: {e}")
                self.message_cache.pop(cid, None)
                self.last_map_refresh.pop(cid, None)

            self.status_cache[cid] = new_fp_list

    @monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(VATSIMMonitor(bot))