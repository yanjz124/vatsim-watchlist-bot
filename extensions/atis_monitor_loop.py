# extensions/atis_monitor_loop.py

import discord
import aiohttp
from discord.ext import commands, tasks
from discord.utils import utcnow
from dateutil import parser
from utils import load_atis_monitor, update_atis_state
from config import CHANNEL_ID


class AtisMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.atis_loop.start()

    async def cog_unload(self):
        self.atis_loop.cancel()

    @tasks.loop(minutes=5)
    async def atis_loop(self):
        """Check ATIS updates every 5 minutes"""
        atis_data = load_atis_monitor()

        if not atis_data:
            return

        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel:
            return

        for airport in atis_data.keys():
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

                    # Get last known state
                    last_codes = atis_data[airport].get('last_codes', {})
                    last_code = last_codes.get(atis_type)

                    # If code changed or this is the first check, send update
                    if last_code != current_code:
                        atis_airport = atis_entry.get("airport", airport)
                        time_str = atis_entry.get("time", "N/A")
                        datis = atis_entry.get("datis", "No ATIS text available.")

                        # Parse updated_at for better display
                        try:
                            dt = parser.isoparse(current_updated)
                            updated_display = dt.strftime("%Y-%m-%d %H:%MZ")
                        except Exception:
                            updated_display = current_updated

                        # Build embed
                        embed = discord.Embed(
                            title=f"{atis_airport} {atis_type.upper()} ATIS - {current_code} - {time_str}Z",
                            description=datis,
                            color=discord.Color.green(),
                            timestamp=utcnow()
                        )
                        embed.set_footer(text=f"Updated: {updated_display}")

                        # Send to channel
                        try:
                            if last_code is None:
                                # First check, don't spam with "new" message
                                pass
                            else:
                                await channel.send(embed=embed)
                        except Exception as e:
                            print(f"Error sending ATIS update for {airport}: {e}")

                        # Update state
                        update_atis_state(airport, atis_type, current_code, current_updated)

            except Exception as e:
                print(f"Error checking ATIS for {airport}: {e}")

    @atis_loop.before_loop
    async def before_atis_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(AtisMonitor(bot))
