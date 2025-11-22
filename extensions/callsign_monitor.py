# extensions/callsign_monitor.py

import discord
from discord.ext import commands
from utils import (
    add_callsign_monitor,
    remove_callsign_monitor,
    load_callsign_monitor
)


class Csmon(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(
        name="csmon",
        invoke_without_command=True,
        case_insensitive=True
    )
    async def csmon(self, ctx):
        """Manage callsign monitoring"""
        await ctx.send(
            "Usage: `!csmon add <RULE> <NAME(optional)>`, "
            "`!csmon remove <RULE>`, `!csmon list`"
        )

    @csmon.command(name="add")
    async def add(self, ctx, *, entry: str):
        parts = entry.strip().split()
        if not parts:
            await ctx.send("Please provide a callsign pattern (e.g., `CXK*`, `ATL_*`, etc.).")
            return

        rule = parts[0].upper()
        name = " ".join(parts[1:]) if len(parts) > 1 else rule  # Default to rule if no name
        add_callsign_monitor(rule, name)
        await ctx.send(f"Monitoring callsign rule `{rule}` as `{name}`.")

    @csmon.command(name="remove")
    async def remove(self, ctx, rule: str):
        remove_callsign_monitor(rule.upper())
        await ctx.send(f"Removed callsign rule `{rule}` from monitoring.")

    @csmon.command(name="list")
    async def list(self, ctx):
        try:
            rule_map = load_callsign_monitor()
            if not rule_map:
                await ctx.send("No callsign rules are currently being monitored.")
                return

            # Discord embeds can have max 25 fields per embed
            # Split into multiple embeds if needed
            rule_items = list(rule_map.items())
            max_fields_per_embed = 25
            
            for i in range(0, len(rule_items), max_fields_per_embed):
                chunk = rule_items[i:i + max_fields_per_embed]
                page_num = (i // max_fields_per_embed) + 1
                total_pages = (len(rule_items) + max_fields_per_embed - 1) // max_fields_per_embed
                
                if total_pages > 1:
                    title = f"Currently Monitored Callsign Rules (Page {page_num}/{total_pages})"
                else:
                    title = "Currently Monitored Callsign Rules"
                
                embed = discord.Embed(title=title, color=discord.Color.orange())
                for rule, name in chunk:
                    embed.add_field(name=rule, value=name, inline=False)
                
                await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"Error: {e}")
            print(f"Error in !csmon list: {e}")


async def setup(bot):
    await bot.add_cog(Csmon(bot))
