# extensions/atis.py

import discord
import aiohttp
from discord.ext import commands
from dateutil import parser
from discord.utils import utcnow
from utils import add_atis_monitor, remove_atis_monitor, load_atis_monitor


class Atis(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def atis(self, ctx, icao: str = None):
        """Get real-world ATIS for an airport"""
        if not icao:
            await ctx.send("Usage: `!atis <ICAO>` or `!atis stations`")
            return

        # Handle special case: list all stations
        if icao.lower() == "stations":
            async with aiohttp.ClientSession() as session:
                async with session.get("https://atis.info/api/stations") as resp:
                    if resp.status != 200:
                        await ctx.send("Failed to retrieve station list.")
                        return
                    stations = await resp.json()

            if not stations:
                await ctx.send("No D-ATIS stations available.")
                return

            # Split into chunks of 25 for Discord embed field limit
            chunks = [stations[i:i + 25] for i in range(0, len(stations), 25)]
            for idx, chunk in enumerate(chunks):
                embed = discord.Embed(
                    title=f"D-ATIS Stations (Page {idx + 1}/{len(chunks)})",
                    description=", ".join(chunk),
                    color=discord.Color.blue()
                )
                await ctx.send(embed=embed)
            return

        # Normal ICAO lookup
        icao = icao.upper()
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://atis.info/api/{icao}") as resp:
                if resp.status != 200:
                    await ctx.send(f"No ATIS found for {icao}.")
                    return
                atis_data = await resp.json()

        if not atis_data:
            await ctx.send(f"No ATIS found for {icao}.")
            return

        # Display each ATIS (arr/dep) in separate embeds
        for atis_entry in atis_data:
            airport = atis_entry.get("airport", icao)
            atis_type = atis_entry.get("type", "N/A").upper()
            code = atis_entry.get("code", "N/A")
            time_str = atis_entry.get("time", "N/A")
            datis = atis_entry.get("datis", "No ATIS text available.")
            updated_at = atis_entry.get("updatedAt", "N/A")

            # Parse updated_at for better display
            try:
                dt = parser.isoparse(updated_at)
                updated_display = dt.strftime("%Y-%m-%d %H:%MZ")
            except Exception:
                updated_display = updated_at

            embed = discord.Embed(
                title=f"{airport} {atis_type} ATIS - {code} - {time_str}Z",
                description=datis,
                color=discord.Color.green(),
                timestamp=utcnow()
            )
            embed.set_footer(text=f"Updated: {updated_display}")
            await ctx.send(embed=embed)

    @commands.group(
        name="atismon",
        invoke_without_command=True,
        case_insensitive=True
    )
    async def atismon(self, ctx):
        """Manage ATIS monitoring"""
        await ctx.send("Usage: `!atismon add <ICAO>`, `!atismon remove <ICAO>`, `!atismon list`")

    @atismon.command(name="add")
    async def atismon_add(self, ctx, icao: str):
        """Add an airport to ATIS monitoring"""
        icao = icao.upper()

        # Verify the airport has D-ATIS available
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://atis.info/api/{icao}") as resp:
                if resp.status != 200:
                    await ctx.send(f"No D-ATIS available for {icao}.")
                    return

        if add_atis_monitor(icao):
            await ctx.send(f"Now monitoring ATIS for {icao}.")
        else:
            await ctx.send(f"{icao} is already being monitored.")

    @atismon.command(name="remove")
    async def atismon_remove(self, ctx, icao: str):
        """Remove an airport from ATIS monitoring"""
        icao = icao.upper()
        if remove_atis_monitor(icao):
            await ctx.send(f"Stopped monitoring ATIS for {icao}.")
        else:
            await ctx.send(f"{icao} is not being monitored.")

    @atismon.command(name="list")
    async def atismon_list(self, ctx):
        """List all monitored airports"""
        atis_data = load_atis_monitor()

        if not atis_data:
            await ctx.send("No airports are currently being monitored for ATIS.")
            return

        airports = list(atis_data.keys())
        embed = discord.Embed(
            title="Monitored ATIS Airports",
            description=", ".join(airports),
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Atis(bot))
