# extensions/coc_monitor_loop.py

import discord
from discord.ext import commands, tasks
from discord.utils import utcnow
import re
from utils import fetch_vatsim_data, build_status_embed, load_a1_monitor, load_a9_monitor
from utils.data_manager import load_fake_names
from config import CHANNEL_ID, atc_rating, pilot_rating
from collections import defaultdict


class CocMonitorLoop(commands.Cog):
    """Real-time VATSIM Code of Conduct A4 monitoring system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.enabled = True  # Default to enabled
        # Default A4 violation alerts to muted unless explicitly enabled
        try:
            from utils.data_manager import load_a4_muted
            self.a4_muted = load_a4_muted()
        except Exception:
            self.a4_muted = True
        self.alerted_users = set()  # Track CID+callsign combinations already alerted
        self.a1_status_cache = {}  # Track A1 keyword matches
        self.a9_status_cache = {}  # Track A9 keyword matches
        self.coc_monitor_loop.start()
    
    async def cog_unload(self):
        self.coc_monitor_loop.cancel()
    
    @tasks.loop(seconds=15)
    async def coc_monitor_loop(self):
        """Monitor for CoC A4 violations and keyword matches every 15 seconds"""
        if not self.enabled:
            return
        
        try:
            data = await fetch_vatsim_data()
            if not isinstance(data, dict):
                return
            
            # Check A4 violations
            violations = await self.check_a4_violations(data)
            if violations:
                await self.send_violation_alerts(violations)
            
            # Check A1 keyword matches
            await self.check_keyword_matches(data, load_a1_monitor(), self.a1_status_cache, "A1")
            
            # Check A9 keyword matches
            await self.check_keyword_matches(data, load_a9_monitor(), self.a9_status_cache, "A9")
        
        except Exception as e:
            print(f"Error in CoC monitor loop: {e}")
    
    @coc_monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
    
    async def check_a4_violations(self, data):
        """
        Check for VATSIM CoC A4(b) name convention violations
        
        A4(b) - Account holders shall connect using only:
        1. Their real, registered name (e.g., Joseph Smith, Joseph S.)
        2. Appropriate shortening of given name + surname (e.g., Joe Smith, Joe S.)
        3. Their real given name (e.g., Joseph)
        4. Appropriate shortening of given name (e.g., Joe)
        5. Their VATSIM CID number
        """
        violations = []
        fake_names = load_fake_names()
        
        # Check all pilots
        for pilot in data.get("pilots", []):
            result = self._check_user_name(pilot, "Pilot", fake_names)
            if result:
                violations.append(result)
        
        # Check all controllers
        for controller in data.get("controllers", []):
            result = self._check_user_name(controller, "Controller", fake_names)
            if result:
                violations.append(result)
        
        return violations
    
    def _check_user_name(self, user_data, user_type, fake_names):
        """Check a single user's name for violations"""
        name_raw = user_data.get("name", "").strip()
        cid = user_data.get("cid")
        callsign = user_data.get("callsign", "N/A")
        violation_reasons = []
        
        # Clean up the name by removing allowed suffixes
        name = name_raw
        
        # Remove home airports at the end (3-4 char alphanumeric codes like NC0, W00, KW91, etc.)
        # This handles cases where people put their home airport after their name
        name = re.sub(r'\s+[A-Z0-9]{3,4}$', '', name).strip()
        
        # If name became empty after cleaning, use original
        if not name:
            name = name_raw
        
        # Check if the cleaned name is just the CID (allowed by CoC)
        # Also allow CID with home airport suffix (e.g., "123456 KW91")
        cid_str = str(cid)
        is_cid_only = (name == cid_str) or re.match(f'^{re.escape(cid_str)}\\s+[A-Z0-9]{{3,4}}$', name_raw)
        
        # Check if name contains numbers
        if re.search(r'\d', name):
            # If name contains numbers, check if it includes their CID
            cid_str = str(cid)
            if cid_str not in name:
                # Numbers present but CID not found - violation
                violation_reasons.append(f"Contains numbers but CID {cid} not found in name")
        
        # Check for special characters (excluding apostrophe ', hyphen -, period ., comma ,, parentheses, underscore _, and question mark ?)
        if re.search(r'[!@#$%^&*+=\[\]{};:<>/\\|`~]', name):
            violation_reasons.append("Contains invalid special characters")
        
        # Check for commas - should not be flagged as violation
        # Commas are allowed in names
        
        # Check fake name patterns with wildcard support
        for pattern in fake_names:
            # Convert wildcard pattern to regex
            regex_pattern = pattern.replace('*', '.*')
            regex_pattern = f'^{regex_pattern}$'
            
            if re.match(regex_pattern, name, re.IGNORECASE):
                violation_reasons.append(f"Matches fake name pattern: {pattern}")
                break
        
        # Check for very short names (less than 2 characters)
        if len(name) < 2:
            violation_reasons.append("Name too short (less than 2 characters)")
        
        # Check for repeated characters (e.g., "AAAA", "XXXX")
        # Allow apostrophes, hyphens, and commas in the check
        # Skip this check if the name is just the CID (allowed by CoC)
        if not is_cid_only:
            clean_name = name.replace(" ", "").replace("'", "").replace("-", "").replace(",", "")
            if len(set(clean_name)) <= 2 and len(clean_name) > 3:
                violation_reasons.append("Repeated characters")
        
        if violation_reasons:
            result = {
                "name": name,
                "cid": cid,
                "callsign": callsign,
                "type": user_type,
                "reasons": violation_reasons,
            }
            
            # Add type-specific data
            if user_type == "Pilot":
                result["lat"] = user_data.get("latitude")
                result["lon"] = user_data.get("longitude")
            elif user_type == "Controller":
                result["frequency"] = user_data.get("frequency")
            
            return result
        
        return None
    
    async def send_violation_alerts(self, violations):
        """Send alerts for new violations only (not already alerted)"""
        # Skip if A4 alerts are muted
        if self.a4_muted:
            return
        
        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel:
            return
        
        for v in violations:
            # Create a unique identifier for this connection
            user_key = f"{v['cid']}:{v['callsign']}"
            
            # Only send alert if we haven't alerted for this CID+callsign combo
            if user_key not in self.alerted_users:
                self.alerted_users.add(user_key)
                
                # CoC A4(b) rule text (shortened for real-time alerts)
                rule_text = (
                    "**VATSIM Code of Conduct A4(b)**: Account holders must use their real name, "
                    "an appropriate shortening, or their CID number."
                )
                
                embed = discord.Embed(
                    title="⚠️ Suspected CoC A4 Violation Detected",
                    description=rule_text,
                    color=discord.Color.orange(),
                    timestamp=utcnow()
                )
                
                field_value = (
                    f"**Name:** {v['name']}\n"
                    f"**CID:** {v['cid']}\n"
                    f"**Callsign:** {v['callsign']}\n"
                    f"**Type:** {v['type']}\n"
                    f"**Issues:** {', '.join(v['reasons'])}"
                )
                
                if v['type'] == "Controller" and v.get('frequency'):
                    field_value += f"\n**Frequency:** {v['frequency']}"
                
                embed.add_field(
                    name="Violation Details",
                    value=field_value,
                    inline=False
                )
                
                embed.set_footer(text="This is a suspected violation and may be a false positive. Manual review recommended.")
                
                await channel.send(embed=embed)
        
        # Clean up alerted_users set - remove users no longer online
        current_user_keys = {f"{v['cid']}:{v['callsign']}" for v in violations}
        self.alerted_users = self.alerted_users.intersection(current_user_keys)

    async def check_keyword_matches(self, data, keywords, status_cache, monitor_name):
        """Check for keyword matches in ATIS, remarks, and routes"""
        if not keywords:
            return
        
        pilots = data.get("pilots", [])
        controllers = data.get("controllers", [])
        
        current_matches = defaultdict(list)
        
        # Add _source to clients
        for client in pilots:
            client["_source"] = "pilot"
        for client in controllers:
            client["_source"] = "controller"
        
        all_clients = pilots + controllers
        
        for client in all_clients:
            source = client.get("_source", "unknown")
            
            # Build searchable text based on client type
            searchable_text = ""
            
            if source == "controller":
                # Check text_atis for controllers
                text_atis = client.get("text_atis", [])
                if text_atis:
                    searchable_text = " ".join(text_atis).upper()
            else:
                # Check remarks and route for pilots
                fp = client.get("flight_plan")
                if fp:
                    remarks = fp.get("remarks", "") or ""
                    route = fp.get("route", "") or ""
                    searchable_text = f"{remarks} {route}".upper()
            
            # Match against all keywords
            for keyword in keywords:
                # Convert wildcard to regex
                if "*" in keyword:
                    # Wildcard present - allow partial matches
                    pattern = keyword.replace("*", ".*").upper()
                else:
                    # No wildcard - match whole word only using word boundaries
                    pattern = r'\b' + re.escape(keyword.upper()) + r'\b'
                
                if re.search(pattern, searchable_text):
                    current_matches[keyword].append(client)
        
        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel:
            return
        
        for keyword, matched_clients in current_matches.items():
            new_fingerprints = []
            
            for client_data in matched_clients:
                callsign = client_data.get("callsign", "N/A")
                source = client_data.get("_source", "unknown")
                is_atc = (source == "controller")
                rating_id = client_data.get("rating") if is_atc else client_data.get("pilot_rating", -1)
                rating = (atc_rating if is_atc else pilot_rating).get(rating_id, f"Unknown ({rating_id})")
                server = client_data.get("server", "N/A")
                start_time = client_data.get("logon_time")
                
                fingerprint = {
                    "status": source,
                    "callsign": callsign,
                    "rating": rating,
                    "server": server,
                    "start_time": start_time,
                    "flight_plan": client_data.get("flight_plan") if source == "pilot" else None,
                }
                new_fingerprints.append(fingerprint)
                
                old_fps = status_cache.get(keyword, [])
                if fingerprint not in old_fps:
                    embed, file = await build_status_embed(
                        client_data=client_data,
                        display_name=f"{monitor_name} Match: {keyword}",
                        rating=rating,
                        is_atc=is_atc,
                        fingerprint=fingerprint
                    )
                    if file:
                        await channel.send(embed=embed, file=file)
                    else:
                        await channel.send(embed=embed)
            
            status_cache[keyword] = new_fingerprints
        
        # Check for disconnections
        for keyword in list(status_cache.keys()):
            if keyword not in current_matches and status_cache[keyword]:
                embed = discord.Embed(
                    title=f"{monitor_name} Match offline: {keyword}",
                    description=f"No clients currently match keyword: {keyword}",
                    color=discord.Color.red()
                )
                await channel.send(embed=embed)
                status_cache[keyword] = []


async def setup(bot):
    await bot.add_cog(CocMonitorLoop(bot))
