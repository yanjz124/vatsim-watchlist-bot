# extensions/type_monitor_loop.py

import discord
from discord.ext import commands, tasks
from utils import load_type_monitor, fetch_vatsim_data, build_status_embed
from config import pilot_rating, CHANNEL_ID
from collections import defaultdict
import re

class TypeMonitorLoop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.status_cache = {}  # pattern -> list of fingerprints
        self.message_cache = {}  # pattern -> discord.Message
        self.type_monitor_loop.start()

    async def cog_unload(self):
        self.type_monitor_loop.cancel()

    def match_type(self, pattern, aircraft_short):
        if not aircraft_short:
            return False
        if "*" not in pattern:
            return pattern == aircraft_short.upper()
        regex_pattern = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
        return re.match(regex_pattern, aircraft_short.upper()) is not None

    @tasks.loop(seconds=15)
    async def type_monitor_loop(self):
        type_rules = load_type_monitor()
        try:
            data = await fetch_vatsim_data()
            if not isinstance(data, dict):
                return
            pilots = data.get("pilots", [])
        except Exception as e:
            print(f"Error fetching VATSIM data: {e}")
            return

        current_matches = defaultdict(list)

        for client in pilots:
            fp = client.get("flight_plan")
            aircraft_short = fp.get("aircraft_short") if fp else None
            for pattern in type_rules:
                if self.match_type(pattern, aircraft_short):
                    current_matches[pattern].append(client)

        for pattern, matched_clients in current_matches.items():
            new_fingerprints = []
            client_data = matched_clients[0]
            aircraft_short = client_data.get("flight_plan", {}).get("aircraft_short", "N/A")
            rating_id = client_data.get("pilot_rating", -1)
            rating = pilot_rating.get(rating_id, f"Unknown ({rating_id})")
            server = client_data.get("server", "N/A")
            start_time = client_data.get("logon_time")

            fingerprint = {
                "aircraft_short": aircraft_short,
                "rating": rating,
                "server": server,
                "start_time": start_time,
                "flight_plan": client_data.get("flight_plan"),
            }
            new_fingerprints.append(fingerprint)

            old_fps = self.status_cache.get(pattern, [])
            channel = self.bot.get_channel(CHANNEL_ID)
            # If new connection (not in cache), send a new message
            if not old_fps:
                embed, file = await build_status_embed(
                    client_data=client_data,
                    display_name=pattern,
                    rating=rating,
                    is_atc=False,
                    fingerprint=fingerprint
                )
                if channel:
                    try:
                        if file:
                            sent = await channel.send(embed=embed, file=file)
                        else:
                            sent = await channel.send(embed=embed)
                        self.message_cache[pattern] = sent
                    except Exception as e:
                        print(f"Error sending new message for {pattern}: {e}")
            # If fingerprint changed but still same connection, edit the message
            elif fingerprint != old_fps[0]:
                embed, file = await build_status_embed(
                    client_data=client_data,
                    display_name=pattern,
                    rating=rating,
                    is_atc=False,
                    fingerprint=fingerprint
                )
                last_msg = self.message_cache.get(pattern)
                if channel and last_msg:
                    try:
                        if file:
                            await last_msg.edit(embed=embed, attachments=[file])
                        else:
                            await last_msg.edit(embed=embed, attachments=[])
                    except Exception as e:
                        print(f"Error editing message for {pattern}: {e}")

            self.status_cache[pattern] = new_fingerprints

        # Check for disconnections
        for pattern in list(self.status_cache.keys()):
            if pattern not in current_matches and self.status_cache[pattern]:
                embed = discord.Embed(
                    title=f"{pattern} is offline",
                    description=f"No pilots currently match {pattern}",
                    color=discord.Color.red()
                )
                channel = self.bot.get_channel(CHANNEL_ID)
                if channel:
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        print(f"Error sending offline message for {pattern}: {e}")
                self.status_cache[pattern] = []
                self.message_cache.pop(pattern, None)

    @type_monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(TypeMonitorLoop(bot))
