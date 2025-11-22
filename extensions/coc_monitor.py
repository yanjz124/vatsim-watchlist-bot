# extensions/coc_monitor.py

import discord
from discord.ext import commands
from discord.utils import utcnow
from typing import Optional
import re
from utils import fetch_vatsim_data, load_a1_monitor, save_a1_monitor, load_a9_monitor, save_a9_monitor
from utils.data_manager import load_fake_names, add_fake_name, remove_fake_name


class CocMonitor(commands.Cog):
    """VATSIM Code of Conduct monitoring system"""
    
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name="cocmonitor")
    async def coc_monitor_toggle(self, ctx, state: Optional[str] = None):
        """Toggle VATSIM CoC real-time monitoring. Usage: !cocmonitor [on/off]"""
        # Get the CocMonitorLoop cog
        coc_loop = self.bot.get_cog("CocMonitorLoop")
        
        if not coc_loop:
            await ctx.send("CoC monitor loop is not loaded.")
            return
        
        if state is None:
            status = "enabled" if coc_loop.enabled else "disabled"
            await ctx.send(f"CoC real-time monitoring is currently **{status}**. Use `!cocmonitor on` or `!cocmonitor off` to toggle.")
            return
        
        state = state.lower()
        if state in ["on", "enable", "enabled", "true", "1"]:
            coc_loop.enabled = True
            await ctx.send("CoC real-time monitoring is now **enabled**.")
        elif state in ["off", "disable", "disabled", "false", "0"]:
            coc_loop.enabled = False
            await ctx.send("CoC real-time monitoring is now **disabled**.")
        else:
            await ctx.send("Invalid option. Use `!cocmonitor on` or `!cocmonitor off`.")
    
    @commands.command(name="cocreset")
    async def coc_reset(self, ctx):
        """Reset CoC monitor alert cache"""
        coc_loop = self.bot.get_cog("CocMonitorLoop")
        
        if not coc_loop:
            await ctx.send("CoC monitor loop is not loaded.")
            return
        
        count = len(coc_loop.alerted_users)
        coc_loop.alerted_users.clear()
        await ctx.send(f"CoC monitor alert cache cleared. ({count} entries removed) Will re-alert for any current violations on next scan.")

    @commands.command(name="a4check")
    async def a4_check(self, ctx):
        """Check for VATSIM CoC A4 name violations"""
        await ctx.send("Checking for CoC A4 name violations...")
        
        try:
            data = await fetch_vatsim_data()
            violations = await self.check_a4_violations(data)
            
            if violations:
                await self.send_a4_violation_embeds(ctx, violations)
            else:
                await ctx.send("No suspected CoC A4 violations detected.")
        
        except Exception as e:
            await ctx.send(f"Error checking CoC violations: {e}")
            print(f"Error in a4check: {e}")
    
    @commands.command(name="fakename")
    async def manage_fake_names(self, ctx, action: Optional[str] = None, *, pattern: Optional[str] = None):
        """Manage fake name patterns. Usage: !fakename [add/remove/list] [pattern]"""
        if action is None:
            await ctx.send("Usage: `!fakename add <pattern>`, `!fakename remove <pattern>`, or `!fakename list`")
            return
        
        action = action.lower()
        
        if action == "list":
            fake_names = load_fake_names()
            
            if not fake_names:
                await ctx.send("No fake name patterns configured.")
                return
            
            embed = discord.Embed(
                title="Fake Name Patterns",
                description="\n".join([f"• `{name}`" for name in fake_names]),
                color=discord.Color.blue(),
                timestamp=utcnow()
            )
            await ctx.send(embed=embed)
        
        elif action == "add":
            if not pattern:
                await ctx.send("Please provide a pattern to add. Usage: `!fakename add <pattern>`")
                return
            
            if add_fake_name(pattern):
                await ctx.send(f"Added fake name pattern: `{pattern}`")
            else:
                await ctx.send(f"Pattern `{pattern}` is already in the list.")
        
        elif action == "remove":
            if not pattern:
                await ctx.send("Please provide a pattern to remove. Usage: `!fakename remove <pattern>`")
                return
            
            if remove_fake_name(pattern):
                await ctx.send(f"Removed fake name pattern: `{pattern}`")
            else:
                await ctx.send(f"Pattern `{pattern}` not found in the list.")
        
        else:
            await ctx.send("Invalid action. Use `add`, `remove`, or `list`.")

    @commands.command(name="a1mon")
    async def a1_monitor_command(self, ctx, action: Optional[str] = None, *, keyword: Optional[str] = None):
        """Manage A1 keyword monitoring. Usage: !a1mon [add/remove/list] [keyword]"""
        
        if action is None:
            await ctx.send("Usage: `!a1mon add <keyword>`, `!a1mon remove <keyword>`, or `!a1mon list`")
            return
        
        action = action.lower()
        
        if action == "list":
            keywords = load_a1_monitor()
            if not keywords:
                await ctx.send("No A1 keywords are currently being monitored.")
                return
            
            embed = discord.Embed(
                title="A1 Monitor - Active Keywords",
                description="\n".join([f"• `{kw}`" for kw in keywords]),
                color=discord.Color.blue()
            )
            embed.set_footer(text="Monitoring ATIS text, remarks, and routes")
            await ctx.send(embed=embed)
        
        elif action == "add":
            if not keyword:
                await ctx.send("Please provide a keyword to monitor. Usage: `!a1mon add <keyword>`")
                return
            
            keywords = load_a1_monitor()
            if keyword in keywords:
                await ctx.send(f"Keyword `{keyword}` is already being monitored.")
                return
            
            keywords.append(keyword)
            save_a1_monitor(keywords)
            await ctx.send(f"Now monitoring keyword: `{keyword}` (supports * wildcard)")
        
        elif action == "remove":
            if not keyword:
                await ctx.send("Please provide a keyword to remove. Usage: `!a1mon remove <keyword>`")
                return
            
            keywords = load_a1_monitor()
            if keyword not in keywords:
                await ctx.send(f"Keyword `{keyword}` is not being monitored.")
                return
            
            keywords.remove(keyword)
            save_a1_monitor(keywords)
            await ctx.send(f"Stopped monitoring keyword: `{keyword}`")
        
        else:
            await ctx.send("Invalid action. Use `add`, `remove`, or `list`.")

    @commands.command(name="a4mon")
    async def a4_monitor_command(self, ctx, action: Optional[str] = None):
        """Toggle A4 violation alerts. Usage: !a4mon [mute/unmute/on/off/status]"""
        coc_loop = self.bot.get_cog("CocMonitorLoop")
        
        if not coc_loop:
            await ctx.send("CoC monitor loop is not loaded.")
            return
        
        if action is None or action.lower() == "status":
            status = "muted" if coc_loop.a4_muted else "unmuted"
            await ctx.send(f"A4 violation alerts are currently **{status}**.")
            return
        
        action = action.lower()
        if action in ["mute", "off", "disable"]:
            coc_loop.a4_muted = True
            await ctx.send("A4 violation alerts are now **muted**. Use `!a4mon unmute` to re-enable.")
        elif action in ["unmute", "on", "enable"]:
            coc_loop.a4_muted = False
            await ctx.send("A4 violation alerts are now **unmuted**.")
        else:
            await ctx.send("Invalid option. Use `!a4mon mute`, `!a4mon unmute`, or `!a4mon status`.")

    @commands.command(name="p56mon")
    async def p56_monitor_command(self, ctx, action: Optional[str] = None):
        """Toggle P56 intrusion alerts. Usage: !p56mon [mute/unmute/on/off/status]"""
        from utils.data_manager import load_p56_muted, save_p56_muted
        
        if action is None or action.lower() == "status":
            status = "muted" if load_p56_muted() else "unmuted"
            await ctx.send(f"P56 intrusion alerts are currently **{status}**.")
            return
        
        action = action.lower()
        if action in ["mute", "off", "disable"]:
            save_p56_muted(True)
            await ctx.send("P56 intrusion alerts are now **muted**. Use `!p56mon unmute` to re-enable.")
        elif action in ["unmute", "on", "enable"]:
            save_p56_muted(False)
            await ctx.send("P56 intrusion alerts are now **unmuted**.")
        else:
            await ctx.send("Invalid option. Use `!p56mon mute`, `!p56mon unmute`, or `!p56mon status`.")

    @commands.command(name="p56")
    async def p56_recent(self, ctx, limit: Optional[int] = 10):
        """Show recent P56 intrusion events. Usage: !p56 [limit]"""
        from config import P56_API_URL
        import aiohttp
        from datetime import datetime, timezone
        
        if limit < 1 or limit > 50:
            await ctx.send("Limit must be between 1 and 50.")
            return
        
        await ctx.send("Fetching P56 intrusion logs...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(P56_API_URL, timeout=10) as resp:
                    if resp.status != 200:
                        await ctx.send(f"API returned error: {resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            await ctx.send(f"Failed to fetch P56 data: {e}")
            return
        
        events = data.get("history", {}).get("events", [])
        current_inside = data.get("history", {}).get("current_inside", {})
        
        if not events and not current_inside:
            await ctx.send("No P56 intrusion events recorded.")
            return
        
        # Combine current_inside (active) and recent events (completed)
        all_entries = []
        
        # Add truly active aircraft from current_inside
        for cid, entry in current_inside.items():
            if entry.get("inside", False):  # Only if actually inside
                all_entries.append({
                    "callsign": entry.get("callsign", "N/A"),
                    "cid": cid,
                    "name": entry.get("name", "Unknown"),
                    "last_seen": entry.get("last_seen", 0),
                    "status": "active",
                    "flight_plan": entry.get("flight_plan"),
                    "p56_buster": entry.get("p56_buster", False)
                })
        
        # Add recent events (exited intrusions)
        for event in reversed(events[-limit:]):
            all_entries.append({
                "callsign": event.get("callsign", "N/A"),
                "cid": event.get("cid", "Unknown"),
                "name": event.get("name", "Unknown"),
                "last_seen": event.get("recorded_at", 0),
                "status": "exited",
                "exit_at": event.get("exit_detected_at") or event.get("exit_confirmed_at"),
                "zones": event.get("zones", []),
                "flight_plan": event.get("flight_plan")
            })
        
        # Sort by timestamp descending
        all_entries.sort(key=lambda x: x.get("last_seen", 0), reverse=True)
        all_entries = all_entries[:limit]
        
        embed = discord.Embed(
            title=f"Recent P56 Intrusion Events ({len(all_entries)})",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        
        for entry in all_entries:
            callsign = entry["callsign"]
            cid = entry["cid"]
            name = entry["name"]
            last_seen = entry["last_seen"]
            
            dt = datetime.fromtimestamp(last_seen, tz=timezone.utc)
            time_str = dt.strftime("%m-%d %H:%M:%SZ")
            
            if entry["status"] == "active":
                status = "🚨 Active"
                if entry.get("p56_buster"):
                    status += " (P56 Buster!)"
            else:
                status = "✅ Exited"
            
            zone_str = ", ".join(entry.get("zones", [])) if entry.get("zones") else "P-56"
            
            fp = entry.get("flight_plan") or {}
            route = ""
            if fp:
                dep = fp.get("departure", "")
                arr = fp.get("arrival", "")
                if dep or arr:
                    route = f"\n{dep} → {arr}"
            
            field_value = f"{status} | CID {cid}\n{name}\n{time_str} | {zone_str}{route}"
            embed.add_field(name=callsign, value=field_value, inline=False)
        
        # Show currently inside count
        inside_count = sum(1 for v in current_inside.values() if v.get("inside", False))
        
        embed.set_footer(text=f"Currently inside P56: {inside_count} aircraft")
        await ctx.send(embed=embed)

    @commands.command(name="a9mon")
    async def a9_monitor_command(self, ctx, action: Optional[str] = None, *, keyword: Optional[str] = None):
        """Manage A9 keyword monitoring. Usage: !a9mon [add/remove/list] [keyword]"""
        
        if action is None:
            await ctx.send("Usage: `!a9mon add <keyword>`, `!a9mon remove <keyword>`, or `!a9mon list`")
            return
        
        action = action.lower()
        
        if action == "list":
            keywords = load_a9_monitor()
            if not keywords:
                await ctx.send("No A9 keywords are currently being monitored.")
                return
            
            embed = discord.Embed(
                title="A9 Monitor - Active Keywords",
                description="\n".join([f"• `{kw}`" for kw in keywords]),
                color=discord.Color.purple()
            )
            embed.set_footer(text="Monitoring ATIS text, remarks, and routes")
            await ctx.send(embed=embed)
        
        elif action == "add":
            if not keyword:
                await ctx.send("Please provide a keyword to monitor. Usage: `!a9mon add <keyword>`")
                return
            
            keywords = load_a9_monitor()
            if keyword in keywords:
                await ctx.send(f"Keyword `{keyword}` is already being monitored.")
                return
            
            keywords.append(keyword)
            save_a9_monitor(keywords)
            await ctx.send(f"Now monitoring keyword: `{keyword}` (supports * wildcard)")
        
        elif action == "remove":
            if not keyword:
                await ctx.send("Please provide a keyword to remove. Usage: `!a9mon remove <keyword>`")
                return
            
            keywords = load_a9_monitor()
            if keyword not in keywords:
                await ctx.send(f"Keyword `{keyword}` is not being monitored.")
                return
            
            keywords.remove(keyword)
            save_a9_monitor(keywords)
            await ctx.send(f"Stopped monitoring keyword: `{keyword}`")
        
        else:
            await ctx.send("Invalid action. Use `add`, `remove`, or `list`.")

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
        
        # Load fake names from data_manager
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
        
        violation_reasons = []
        
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

    async def send_a4_violation_embeds(self, channel, violations):
        """Send A4 violation reports in paginated embeds"""
        max_fields_per_embed = 25
        
        # CoC A4(b) rule text
        rule_text = (
            "**VATSIM Code of Conduct A4(b)**: Account holders shall connect using only:\n"
            "1. Their real, registered name (e.g., Joseph Smith)\n"
            "2. Appropriate shortening of given name + surname (e.g., Joe Smith)\n"
            "3. Their real given name (e.g., Joseph)\n"
            "4. Appropriate shortening of given name (e.g., Joe)\n"
            "5. Their VATSIM CID number"
        )
        
        for i in range(0, len(violations), max_fields_per_embed):
            chunk = violations[i:i + max_fields_per_embed]
            page_num = (i // max_fields_per_embed) + 1
            total_pages = (len(violations) + max_fields_per_embed - 1) // max_fields_per_embed
            
            if total_pages > 1:
                title = f"Suspected CoC A4 Violations (Page {page_num}/{total_pages})"
            else:
                title = f"Suspected CoC A4 Violations ({len(violations)} found)"
            
            embed = discord.Embed(
                title=title,
                description=rule_text if page_num == 1 else None,
                color=discord.Color.orange(),
                timestamp=utcnow()
            )
            
            for v in chunk:
                field_value = (
                    f"**CID:** {v['cid']}\n"
                    f"**Callsign:** {v['callsign']}\n"
                    f"**Type:** {v['type']}\n"
                    f"**Issues:** {', '.join(v['reasons'])}"
                )
                
                if v['type'] == "Controller" and v.get('frequency'):
                    field_value += f"\n**Frequency:** {v['frequency']}"
                
                embed.add_field(
                    name=f"{v['name']}",
                    value=field_value,
                    inline=False
                )
            
            embed.set_footer(text="These are suspected violations and may include false positives. Manual review recommended.")
            
            await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(CocMonitor(bot))
