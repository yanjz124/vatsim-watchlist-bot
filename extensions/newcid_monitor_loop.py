# extensions/newcid_monitor_loop.py

import discord
from discord.ext import commands, tasks
from discord.utils import utcnow
from datetime import timezone
from utils import fetch_vatsim_data, build_status_embed
from config import CHANNEL_ID, atc_rating, pilot_rating
import json
import os


class NewCidMonitorLoop(commands.Cog):
    """Monitor for the newest (highest) CID on VATSIM network"""
    
    def __init__(self, bot):
        self.bot = bot
        self.highest_cid = self._load_highest_cid()
        self.alerted_cids = set()  # Track CIDs we've already alerted for
        self.muted = False  # Default to unmuted (alerts enabled)
        self.newcid_monitor_loop.start()
    
    async def cog_unload(self):
        self.newcid_monitor_loop.cancel()
    
    def _load_highest_cid(self):
        """Load the highest CID from file"""
        try:
            if os.path.exists("data/highest_cid.json"):
                with open("data/highest_cid.json", "r") as f:
                    data = json.load(f)
                    return data.get("highest_cid", 0)
        except Exception as e:
            print(f"Error loading highest CID: {e}")
        return 0
    
    def _save_highest_cid(self, cid):
        """Save the highest CID to file"""
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/highest_cid.json", "w") as f:
                json.dump({"highest_cid": cid}, f)
        except Exception as e:
            print(f"Error saving highest CID: {e}")
    
    @tasks.loop(seconds=15)
    async def newcid_monitor_loop(self):
        """Monitor for new highest CIDs every 15 seconds"""
        try:
            data = await fetch_vatsim_data()
            if not isinstance(data, dict):
                return
            pilots = data.get("pilots", [])
            controllers = data.get("controllers", [])
            atis = data.get("atis", [])

            # Add source type to all clients
            for client in pilots:
                client["_source"] = "pilot"
            for client in controllers:
                client["_source"] = "controller"
            for client in atis:
                client["_source"] = "atis"

            all_clients = pilots + controllers + atis

            # Find the highest CID currently online
            if not all_clients:
                return

            current_highest = max(int(client.get("cid", 0)) for client in all_clients)
            
            # Check if we found a new highest CID
            if current_highest > self.highest_cid:
                # Find the client(s) with this CID
                new_cid_clients = [c for c in all_clients if int(c.get("cid", 0)) == current_highest]
                
                # Update our records
                old_highest = self.highest_cid
                self.highest_cid = current_highest
                self._save_highest_cid(current_highest)
                
                # Send alerts for each connection with the new CID (if not muted)
                if not self.muted and current_highest not in self.alerted_cids:
                    self.alerted_cids.add(current_highest)
                    await self.send_new_cid_alerts(new_cid_clients, old_highest)
        
        except Exception as e:
            print(f"Error in new CID monitor loop: {e}")
    
    @newcid_monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
    
    async def send_new_cid_alerts(self, clients, old_highest):
        """Send alerts for new highest CID detected"""
        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel:
            return
        
        for client_data in clients:
            cid = client_data.get("cid")
            name = client_data.get("name", "N/A")
            callsign = client_data.get("callsign", "N/A")
            source = client_data.get("_source", "unknown")
            is_atc = (source == "controller")
            is_atis = (source == "atis")
            
            # Determine rating
            if is_atc or is_atis:
                rating_id = client_data.get("rating", -1)
                rating = atc_rating.get(rating_id, f"Unknown ({rating_id})")
            else:
                rating_id = client_data.get("pilot_rating", -1)
                rating = pilot_rating.get(rating_id, f"Unknown ({rating_id})")
            
            server = client_data.get("server", "N/A")
            logon_time = client_data.get("logon_time", "N/A")
            
            # Create fingerprint for build_status_embed
            fingerprint = {
                "status": source,
                "callsign": callsign,
                "rating": rating,
                "server": server,
                "start_time": logon_time,
                "flight_plan": client_data.get("flight_plan") if source == "pilot" else None,
            }
            
            # Build embed using the standard function
            embed, file = await build_status_embed(
                client_data=client_data,
                display_name=name,
                rating=rating,
                is_atc=(is_atc or is_atis),
                fingerprint=fingerprint
            )
            
            # Customize for new CID alert
            embed.color = discord.Color.gold()
            embed.title = f"🎉 New Highest CID Detected: {int(cid)}"

            # Insert previous highest and difference fields before the API fields
            # Count current fields to insert at right position (before we add API data)
            current_field_count = len(embed.fields)
            
            # We'll add these right before fetching API data
            if old_highest > 0:
                embed.insert_field_at(
                    current_field_count,
                    name="Previous Highest CID",
                    value=f"{int(old_highest)}",
                    inline=True
                )
                embed.insert_field_at(
                    current_field_count + 1,
                    name="Difference",
                    value=f"+{int(cid) - int(old_highest)}",
                    inline=True
                )
            else:
                embed.insert_field_at(
                    current_field_count,
                    name="Status",
                    value="First record",
                    inline=True
                )

            # Fetch registration date and last rating change from VATSIM API
            import aiohttp
            from dateutil import parser as dateparser
            
            url = f"https://api.vatsim.net/api/ratings/{cid}/"
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

            embed.set_footer(text=f"New highest CID on the network")

            # Send the message
            if file:
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(NewCidMonitorLoop(bot))
