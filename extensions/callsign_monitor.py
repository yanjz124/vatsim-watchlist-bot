# extensions/callsign_monitor.py

import time

import discord
from discord.ext import commands
from utils import (
    add_callsign_monitor,
    remove_callsign_monitor,
    load_callsign_monitor,
    load_callsign_mutes,
    add_callsign_mute,
    remove_callsign_mute,
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
        add_callsign_monitor(ctx.guild.id, rule, name)
        await ctx.send(f"Monitoring callsign rule `{rule}` as `{name}`.")

    @csmon.command(name="remove")
    async def remove(self, ctx, rule: str):
        remove_callsign_monitor(ctx.guild.id, rule.upper())
        await ctx.send(f"Removed callsign rule `{rule}` from monitoring.")

    @csmon.command(name="list")
    async def list(self, ctx):
        try:
            rule_map = load_callsign_monitor(ctx.guild.id)
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


class Csmute(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="csmute")
    async def csmute(self, ctx, *args):
        """Mute callsigns (supports `*` wildcards) from triggering csmon notifications.

        Usage:
          !csmute                  — list current mutes
          !csmute CALLSIGN         — mute for 24h (default)
          !csmute CALLSIGN <hours> — mute for <hours>; 0 or negative = permanent
          !csmute -CALLSIGN        — unmute
        """
        if not args:
            await self._send_list(ctx)
            return

        target = args[0]
        if target.startswith("-") and len(target) > 1:
            pattern = target[1:].upper()
            if remove_callsign_mute(ctx.guild.id, pattern):
                await ctx.send(f"Unmuted `{pattern}`.")
            else:
                await ctx.send(f"`{pattern}` is not muted.")
            return

        pattern = target.upper()
        hours = 24
        if len(args) > 1:
            try:
                hours = int(args[1])
            except ValueError:
                await ctx.send(f"Invalid duration `{args[1]}` — expected an integer (hours).")
                return

        pat, expires_at = add_callsign_mute(ctx.guild.id, pattern, hours)
        if expires_at is None:
            await ctx.send(f"Muted `{pat}` **permanently**.")
        else:
            await ctx.send(f"Muted `{pat}` until <t:{expires_at}:f> (<t:{expires_at}:R>).")

    async def _send_list(self, ctx):
        mutes = load_callsign_mutes(ctx.guild.id)
        if not mutes:
            await ctx.send("No callsigns are currently muted.")
            return

        now = int(time.time())
        permanent, timed = [], []
        for pat, exp in mutes.items():
            if exp is None:
                permanent.append(pat)
            else:
                timed.append((pat, exp))

        timed.sort(key=lambda x: x[1])
        permanent.sort()

        lines = []
        if timed:
            lines.append(f"**Timed — {len(timed)}**")
            for pat, exp in timed:
                remaining = exp - now
                lines.append(f"`{pat}` — expires <t:{exp}:R> ({_fmt_remaining(remaining)})")
        if permanent:
            if lines:
                lines.append("")
            lines.append(f"**Permanent — {len(permanent)}**")
            for pat in permanent:
                lines.append(f"`{pat}`")

        embed = discord.Embed(
            title=f"Muted Callsigns ({len(mutes)})",
            description="\n".join(lines),
            color=discord.Color.dark_grey(),
        )
        await ctx.send(embed=embed)


def _fmt_remaining(seconds):
    if seconds <= 0:
        return "expired"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h >= 24:
        d, h = divmod(h, 24)
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


async def setup(bot):
    await bot.add_cog(Csmon(bot))
    await bot.add_cog(Csmute(bot))
