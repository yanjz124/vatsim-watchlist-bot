# extensions/callsign_monitor_loop.py

import re
from discord.ext import tasks
from collections import defaultdict
from extensions.base_monitor import VatsimMonitorLoop
from utils import load_callsign_monitor, is_callsign_muted


class CallsignMonitor(VatsimMonitorLoop):
    """Monitor callsign patterns on the VATSIM network."""

    INCLUDE_CONTROLLERS = True
    ENABLE_MAP_REFRESH = True

    def __init__(self, bot):
        super().__init__(bot)
        self.callsign_monitor_loop.start()

    async def cog_unload(self):
        self.callsign_monitor_loop.cancel()

    def load_config(self):
        return load_callsign_monitor()

    def match_clients(self, pilots, controllers):
        callsigns = self.load_config()
        current_matches = defaultdict(list)
        for client in pilots + controllers:
            callsign = client.get("callsign", "").upper()
            if is_callsign_muted(callsign):
                continue
            for mon in callsigns:
                pattern = mon.replace("*", ".*").upper()
                if re.fullmatch(pattern, callsign):
                    current_matches[mon].append(client)
        return dict(current_matches)

    def get_display_name(self, key, client_data):
        return key

    def get_offline_description(self, key):
        return f"{key} is offline", f"No clients currently match {key}"

    @tasks.loop(seconds=15)
    async def callsign_monitor_loop(self):
        await self.run_monitor_cycle()

    @callsign_monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(CallsignMonitor(bot))
