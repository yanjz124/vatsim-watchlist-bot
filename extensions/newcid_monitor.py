# extensions/newcid_monitor.py


import discord
from discord.ext import commands
from discord.utils import utcnow
from datetime import timezone
from typing import Optional


class NewCidMonitor(commands.Cog):
    """Commands for managing new CID monitoring"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="newcid")
    async def newcid_command(self, ctx, action: Optional[str] = None):
        """View highest CID and manage alerts. Usage: !newcid [mute/unmute]"""
        # Get the NewCidMonitorLoop cog
        newcid_loop = self.bot.get_cog("NewCidMonitorLoop")
        
        if not newcid_loop:
            await ctx.send("New CID monitor loop is not loaded.")
            return
        
        # No action - show current highest CID
        if action is None:
            highest_cid = newcid_loop.highest_cid
            mute_status = "muted" if newcid_loop.muted else "unmuted"

            embed = discord.Embed(
                title="📊 Highest CID Tracker",
                description=f"The highest CID currently tracked on the network.",
                color=discord.Color.blue(),
                timestamp=utcnow()
            )

            if highest_cid > 0:
                embed.add_field(
                    name="Highest CID",
                    value=f"**{int(highest_cid)}**",
                    inline=False
                )

                # Fetch registration date and last rating change
                import aiohttp
                from dateutil import parser as dateparser
                
                url = f"https://api.vatsim.net/api/ratings/{highest_cid}/"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            reg_date = data.get("reg_date", "N/A")
                            last_change = data.get("lastratingchange", "N/A")
                            
                            # Format registration date with Discord timestamp
                            if reg_date != "N/A":
                                try:
                                    reg_dt = dateparser.parse(reg_date)
                                    # Ensure UTC timezone
                                    if reg_dt.tzinfo is None:
                                        reg_dt = reg_dt.replace(tzinfo=timezone.utc)
                                    else:
                                        reg_dt = reg_dt.astimezone(timezone.utc)
                                    reg_str = reg_dt.strftime("%Y-%m-%dT%H:%MZ")
                                    reg_timestamp = int(reg_dt.timestamp())
                                    reg_formatted = f"{reg_str}\n<t:{reg_timestamp}:R>"
                                except:
                                    reg_formatted = reg_date
                            else:
                                reg_formatted = "N/A"
                            
                            # Format last rating change with Discord timestamp
                            if last_change != "N/A":
                                try:
                                    change_dt = dateparser.parse(last_change)
                                    # Ensure UTC timezone
                                    if change_dt.tzinfo is None:
                                        change_dt = change_dt.replace(tzinfo=timezone.utc)
                                    else:
                                        change_dt = change_dt.astimezone(timezone.utc)
                                    change_str = change_dt.strftime("%Y-%m-%dT%H:%MZ")
                                    change_timestamp = int(change_dt.timestamp())
                                    change_formatted = f"{change_str}\n<t:{change_timestamp}:R>"
                                except:
                                    change_formatted = last_change
                            else:
                                change_formatted = "N/A"
                            
                            embed.add_field(
                                name="Registration Date",
                                value=reg_formatted,
                                inline=True
                            )
                            embed.add_field(
                                name="Last Rating Change",
                                value=change_formatted,
                                inline=True
                            )
                        else:
                            embed.add_field(
                                name="Registration Date",
                                value="N/A",
                                inline=True
                            )
                            embed.add_field(
                                name="Last Rating Change",
                                value="N/A",
                                inline=True
                            )
            else:
                embed.add_field(
                    name="Highest CID",
                    value="No data yet (waiting for first scan)",
                    inline=False
                )

            embed.add_field(
                name="Alert Status",
                value=f"Alerts are currently **{mute_status}**",
                inline=False
            )

            embed.set_footer(text="Use !newcid mute/unmute to toggle alerts")

            await ctx.send(embed=embed)
            return
        
        action = action.lower()
        
        # Handle mute action
        if action in ["mute", "off", "disable"]:
            if newcid_loop.muted:
                await ctx.send("New CID alerts are already **muted**.")
            else:
                newcid_loop.muted = True
                await ctx.send("New CID alerts are now **muted**. 🔇")
        
        # Handle unmute action
        elif action in ["unmute", "on", "enable"]:
            if not newcid_loop.muted:
                await ctx.send("New CID alerts are already **unmuted**.")
            else:
                newcid_loop.muted = False
                await ctx.send("New CID alerts are now **unmuted**. 🔔")
        
        # Handle status action
        elif action == "status":
            mute_status = "muted" if newcid_loop.muted else "unmuted"
            highest_cid = newcid_loop.highest_cid
            
            status_msg = f"**Highest CID:** {highest_cid:,}\n" if highest_cid > 0 else "**Highest CID:** No data yet\n"
            status_msg += f"**Alerts:** {mute_status}"
            
            await ctx.send(status_msg)
        
        # Invalid action
        else:
            await ctx.send("Invalid option. Use `!newcid`, `!newcid mute`, `!newcid unmute`, or `!newcid status`.")
    
    @commands.command(name="resetcid")
    async def reset_cid(self, ctx):
        """Reset the highest CID tracker (admin use)"""
        newcid_loop = self.bot.get_cog("NewCidMonitorLoop")
        
        if not newcid_loop:
            await ctx.send("New CID monitor loop is not loaded.")
            return
        
        old_cid = newcid_loop.highest_cid
        newcid_loop.highest_cid = 0
        newcid_loop.alerted_cids.clear()
        newcid_loop._save_highest_cid(0)
        
        embed = discord.Embed(
            title="🔄 Highest CID Reset",
            description=f"The highest CID tracker has been reset.",
            color=discord.Color.orange(),
            timestamp=utcnow()
        )
        
        embed.add_field(
            name="Previous Highest",
            value=f"{old_cid:,}" if old_cid > 0 else "No data",
            inline=True
        )
        
        embed.add_field(
            name="Current Highest",
            value="0 (reset)",
            inline=True
        )
        
        embed.set_footer(text="The tracker will detect the highest CID on the next scan.")
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(NewCidMonitor(bot))
