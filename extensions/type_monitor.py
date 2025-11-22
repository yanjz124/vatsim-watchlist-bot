# extensions/type_monitor.py

import discord
from discord.ext import commands
from utils import (
    add_type_monitor,
    remove_type_monitor,
    load_type_monitor
)

class Typemon(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(
        name="typemon",
        invoke_without_command=True,
        case_insensitive=True
    )
    async def typemon(self, ctx):
        """Manage aircraft type monitoring"""
        await ctx.send(
            "Usage: `!typemon add <PATTERN> <NAME(optional)>`, "
            "`!typemon remove <PATTERN>`, `!typemon list`"
        )

    @typemon.command(name="add")
    async def add(self, ctx, *, entry: str):
        parts = entry.strip().split()
        if not parts:
            await ctx.send("Please provide an aircraft type pattern (e.g., `B738`, `A320*`, etc.).")
            return

        pattern = parts[0].upper()
        name = " ".join(parts[1:]) if len(parts) > 1 else pattern  # Default to pattern if no name
        add_type_monitor(pattern, name)
        await ctx.send(f"Monitoring aircraft type `{pattern}` as `{name}`.")

    @typemon.command(name="remove")
    async def remove(self, ctx, pattern: str):
        remove_type_monitor(pattern.upper())
        await ctx.send(f"Removed aircraft type `{pattern}` from monitoring.")

    @typemon.command(name="list")
    async def list(self, ctx):
        try:
            rule_map = load_type_monitor()
            if not rule_map:
                await ctx.send("No aircraft types are currently being monitored.")
                return

            rule_items = list(rule_map.items())
            max_fields_per_embed = 25
            for i in range(0, len(rule_items), max_fields_per_embed):
                chunk = rule_items[i:i + max_fields_per_embed]
                page_num = (i // max_fields_per_embed) + 1
                total_pages = (len(rule_items) + max_fields_per_embed - 1) // max_fields_per_embed
                if total_pages > 1:
                    title = f"Currently Monitored Aircraft Types (Page {page_num}/{total_pages})"
                else:
                    title = "Currently Monitored Aircraft Types"
                embed = discord.Embed(title=title, color=discord.Color.teal())
                for pattern, name in chunk:
                    embed.add_field(name=pattern, value=name, inline=False)
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Error: {e}")
            print(f"Error in !typemon list: {e}")

async def setup(bot):
    await bot.add_cog(Typemon(bot))
