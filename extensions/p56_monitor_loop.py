# extensions/p56_monitor_loop.py

import discord
from discord.ext import commands, tasks
import aiohttp
from datetime import datetime, timezone
from utils.data_manager import load_p56_muted, load_p56_seen_events, save_p56_seen_events
from config import CHANNEL_ID, P56_API_URL


class P56Monitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.seen_events = load_p56_seen_events()
        self.p56_monitor_loop.start()

    async def cog_unload(self):
        self.p56_monitor_loop.cancel()

    @tasks.loop(seconds=30)
    async def p56_monitor_loop(self):
        """Poll P56 API and send alerts for new intrusions"""
        if load_p56_muted():
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(P56_API_URL, timeout=10) as resp:
                    if resp.status != 200:
                        print(f"[P56 Monitor] API returned {resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            print(f"[P56 Monitor] Failed to fetch API: {e}")
            return

        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel:
            return

        # Check for events (completed/exited intrusions)
        events = data.get("history", {}).get("events", [])
        new_events = []
        for event in events:
            recorded = event.get("recorded_at")
            if not recorded:
                continue
            event_id = f"{event.get('identifier', 'unknown')}_{recorded}"
            if event_id not in self.seen_events:
                new_events.append(event)
                self.seen_events.add(event_id)

        # Send alerts for new events (most recent first, limit to avoid spam)
        for event in reversed(new_events[-5:]):
            embed = self.build_p56_embed(event, from_events=True)
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"[P56 Monitor] Failed to send alert: {e}")

        if new_events:
            save_p56_seen_events(self.seen_events)

    def build_p56_embed(self, event, from_events=False):
        """Build embed for a P56 intrusion event"""
        cid = event.get("cid", "Unknown")
        callsign = event.get("callsign", "N/A")
        name = event.get("name", "Unknown")
        zones = event.get("zones", [])
        recorded_at = event.get("recorded_at", 0)
        exit_detected = event.get("exit_detected_at") or event.get("exit_confirmed_at")

        title = f"🚨 P56 Intrusion Detected: {callsign}"
        if exit_detected:
            title = f"✅ P56 Exit Confirmed: {callsign}"

        embed = discord.Embed(
            title=title,
            color=discord.Color.red() if not exit_detected else discord.Color.green(),
            timestamp=datetime.fromtimestamp(recorded_at, tz=timezone.utc) if recorded_at else datetime.now(timezone.utc)
        )

        embed.add_field(name="CID", value=str(cid), inline=True)
        embed.add_field(name="Callsign", value=callsign, inline=True)
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Zones", value=", ".join(zones) if zones else "P-56", inline=False)

        # Flight plan details
        fp = event.get("flight_plan")
        if fp:
            aircraft = fp.get("aircraft_short") or fp.get("aircraft_faa") or fp.get("aircraft", "N/A")
            dep = fp.get("departure", "N/A") or "N/A"
            arr = fp.get("arrival", "N/A") or "N/A"
            route = fp.get("route", "") or ""
            remarks = fp.get("remarks", "") or ""
            squawk = fp.get("assigned_transponder", "N/A")

            if aircraft != "N/A":
                embed.add_field(name="Aircraft", value=aircraft, inline=True)
            if squawk:
                embed.add_field(name="Squawk", value=squawk, inline=True)
            if dep != "N/A" or arr != "N/A":
                embed.add_field(name="Route", value=f"{dep} → {arr}", inline=True)
            if route and len(route) > 5:
                embed.add_field(name="Full Route", value=route[:1024], inline=False)
            if remarks and len(remarks) > 3:
                embed.add_field(name="Remarks", value=remarks[:1024], inline=False)

        # Position summary
        pre_positions = event.get("pre_positions", [])
        intrusion_positions = event.get("intrusion_positions", [])
        post_positions = event.get("post_positions", [])
        
        if intrusion_positions:
            first = intrusion_positions[0]
            last = intrusion_positions[-1]
            first_time = datetime.fromtimestamp(first.get("ts", 0), tz=timezone.utc).strftime("%H:%M:%SZ")
            last_time = datetime.fromtimestamp(last.get("ts", 0), tz=timezone.utc).strftime("%H:%M:%SZ")
            
            track_summary = f"**Entry:** {first.get('lat', 0):.5f}, {first.get('lon', 0):.5f} @ {first_time}\n"
            track_summary += f"**Exit:** {last.get('lat', 0):.5f}, {last.get('lon', 0):.5f} @ {last_time}\n"
            track_summary += f"**Duration:** {len(intrusion_positions)} position updates"
            
            embed.add_field(name="P56 Track", value=track_summary, inline=False)
        
        # Latest position from current_inside entries
        latest_pos = event.get("latest_position") or event.get("last_position")
        if latest_pos and not intrusion_positions:
            lat = latest_pos.get("lat")
            lon = latest_pos.get("lon")
            if lat and lon:
                embed.add_field(name="Last Position", value=f"{lat:.5f}, {lon:.5f}", inline=False)

        if exit_detected:
            exit_dt = datetime.fromtimestamp(exit_detected, tz=timezone.utc)
            embed.add_field(name="Exit Detected", value=exit_dt.strftime("%Y-%m-%d %H:%M:%SZ"), inline=False)

        embed.set_footer(text="P56 Intrusion Monitor")
        return embed

    @p56_monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(P56Monitor(bot))
