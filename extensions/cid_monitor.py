# extensions/cid_monitor.py

import discord
from discord.ext import commands
import aiohttp
from utils import add_cid_to_monitor, remove_cid_from_monitor, get_cid_to_monitor


class Cidmon(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(
        name="cidmon",
        invoke_without_command=True,
        case_insensitive=True
    )
    async def cidmon(self, ctx):
        """Manage CID monitoring"""
        await ctx.send("Usage: `!cidmon add <CID1> name1(optional), <CID2> name2(optional),...`, `!cidmon remove <CID>`, `!cidmon list`")

    @cidmon.command(name="add")
    async def add(self, ctx, *, entries: str):
        chunks = [e.strip() for e in entries.split(',') if e.strip()]

        for i, chunk in enumerate(chunks):
            parts = chunk.split()
            if not parts:
                continue

            cid_part = parts[0]
            if not cid_part.isdigit():
                await ctx.send(f"Invalid CID: `{cid_part}`")
                continue

            cid = int(cid_part)
            name = " ".join(parts[1:]) if len(parts) > 1 else None
            resolved_name = name

            # Try to pull name from VATUSA only if name not given
            if not name:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f"https://api.vatusa.net/v2/user/{cid}") as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                fname = data["data"].get("fname")
                                lname = data["data"].get("lname")
                                if fname and lname:
                                    resolved_name = f"{fname} {lname}"
                except Exception as e:
                    print(f"Error fetching name for CID {cid}: {e}")

            if not resolved_name:
                resolved_name = str(cid)

            add_cid_to_monitor(cid, resolved_name)
            await ctx.send(f"Monitoring CID {cid} as `{resolved_name}`.")

    @cidmon.command(name="remove")
    async def monitor_remove(self, ctx, cid: int):
        remove_cid_from_monitor(cid)
        await ctx.send(f"Removed CID `{cid}` from monitoring.")

    @cidmon.command(name="list")
    async def list(self, ctx):
        try:
            cid_map = get_cid_to_monitor()
            if not cid_map:
                await ctx.send("No CIDs are currently being monitored.")
                return

            # Discord embeds can have max 25 fields per embed
            # Split into multiple embeds if needed
            cid_items = list(cid_map.items())
            max_fields_per_embed = 25
            
            for i in range(0, len(cid_items), max_fields_per_embed):
                chunk = cid_items[i:i + max_fields_per_embed]
                page_num = (i // max_fields_per_embed) + 1
                total_pages = (len(cid_items) + max_fields_per_embed - 1) // max_fields_per_embed
                
                if total_pages > 1:
                    title = f"Currently Monitored CIDs (Page {page_num}/{total_pages})"
                else:
                    title = "Currently Monitored CIDs"
                
                embed = discord.Embed(title=title, color=discord.Color.blue())
                for cid, name in chunk:
                    embed.add_field(name=str(cid), value=name, inline=False)
                
                await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"Error: {e}")
            print(f"Error in !monitor list: {e}")


async def setup(bot):
    await bot.add_cog(Cidmon(bot))
