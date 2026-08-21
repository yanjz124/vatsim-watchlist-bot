# extensions/atis_monitor_loop.py

import discord
import aiohttp
from discord.ext import commands, tasks
from discord.utils import utcnow
from dateutil import parser
from utils import load_atis_monitor, update_atis_state, iter_feed_channels


class AtisMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.atis_loop.start()

    async def cog_unload(self):
        self.atis_loop.cancel()

    @tasks.loop(minutes=5)
    async def atis_loop(self):
        """Check ATIS updates every 5 minutes.

        Guilds keep their own airport lists, but the upstream ATIS is the
        same for everybody -- so build the union of watched airports, fetch
        each one once, then dispatch to whichever guilds watch it. Last-seen
        codes stay per guild, so a server that adds an airport later doesn't
        inherit another server's state.
        """
        # airport -> [(guild_id, channel, that guild's stored atis state)]
        watchers = {}
        for guild_id, channel in iter_feed_channels(self.bot, 'atis'):
            atis_data = load_atis_monitor(guild_id)
            for airport in atis_data:
                watchers.setdefault(airport, []).append((guild_id, channel, atis_data))

        if not watchers:
            return

        for airport, subscribers in watchers.items():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"https://atis.info/api/{airport}") as resp:
                        if resp.status != 200:
                            continue
                        current_atis = await resp.json()

                if not current_atis:
                    continue

                # Check each ATIS entry (arr/dep) for changes
                for atis_entry in current_atis:
                    atis_type = atis_entry.get("type", "N/A")
                    current_code = atis_entry.get("code", "N/A")
                    current_updated = atis_entry.get("updatedAt", "N/A")

                    atis_airport = atis_entry.get("airport", airport)
                    time_str = atis_entry.get("time", "N/A")
                    datis = atis_entry.get("datis", "No ATIS text available.")

                    try:
                        dt = parser.isoparse(current_updated)
                        updated_display = dt.strftime("%Y-%m-%d %H:%MZ")
                    except Exception:
                        updated_display = current_updated

                    for guild_id, channel, atis_data in subscribers:
                        last_codes = atis_data.get(airport, {}).get('last_codes', {})
                        last_code = last_codes.get(atis_type)
                        if last_code == current_code:
                            continue

                        # First observation for a guild seeds state silently
                        # rather than announcing an ATIS that didn't just change.
                        if last_code is not None:
                            embed = discord.Embed(
                                title=f"{atis_airport} {atis_type.upper()} ATIS - {current_code} - {time_str}Z",
                                description=datis,
                                color=discord.Color.green(),
                                timestamp=utcnow()
                            )
                            embed.set_footer(text=f"Updated: {updated_display}")
                            try:
                                await channel.send(embed=embed)
                            except Exception as e:
                                print(f"Error sending ATIS update for {airport} "
                                      f"in guild {guild_id}: {e}")

                        update_atis_state(guild_id, airport, atis_type,
                                          current_code, current_updated)

            except Exception as e:
                print(f"Error checking ATIS for {airport}: {e}")

    @atis_loop.before_loop
    async def before_atis_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(AtisMonitor(bot))
