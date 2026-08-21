# extensions/type_monitor_loop.py

import re
from discord.ext import tasks
from collections import defaultdict
from extensions.base_monitor import VatsimMonitorLoop
from utils import load_type_monitor


class TypeMonitorLoop(VatsimMonitorLoop):
    """Monitor aircraft type patterns on the VATSIM network (pilots only)."""

    INCLUDE_CONTROLLERS = False
    ENABLE_MAP_REFRESH = False

    def __init__(self, bot):
        super().__init__(bot)
        self.type_monitor_loop.start()

    async def cog_unload(self):
        self.type_monitor_loop.cancel()

    def load_config(self, guild_id):
        return load_type_monitor(guild_id)

    def match_clients(self, guild_id, pilots, controllers):
        type_rules = self.load_config(guild_id)
        current_matches = defaultdict(list)
        for client in pilots:
            fp = client.get("flight_plan")
            aircraft_short = fp.get("aircraft_short") if fp else None
            if not aircraft_short:
                continue
            for pattern in type_rules:
                if self._match_type(pattern, aircraft_short):
                    current_matches[pattern].append(client)
        return dict(current_matches)

    def _match_type(self, pattern, aircraft_short):
        if "*" not in pattern:
            return pattern.upper() == aircraft_short.upper()
        regex_pattern = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
        return re.match(regex_pattern, aircraft_short.upper()) is not None

    def get_display_name(self, guild_id, key, client_data):
        return key

    def get_offline_description(self, guild_id, key):
        return f"{key} is offline", f"No pilots currently match {key}"

    @tasks.loop(seconds=15)
    async def type_monitor_loop(self):
        await self.run_monitor_cycle()

    @type_monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(TypeMonitorLoop(bot))
