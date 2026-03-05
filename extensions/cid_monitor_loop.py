# extensions/cid_monitor_loop.py

from discord.ext import tasks
from collections import defaultdict
from extensions.base_monitor import VatsimMonitorLoop
from utils import get_cid_to_monitor


class VATSIMMonitor(VatsimMonitorLoop):
    """Monitor specific CIDs on the VATSIM network."""

    INCLUDE_CONTROLLERS = True
    ENABLE_MAP_REFRESH = True

    def __init__(self, bot):
        super().__init__(bot)
        self.monitor_loop.start()

    async def cog_unload(self):
        self.monitor_loop.cancel()

    def load_config(self):
        return get_cid_to_monitor()

    def match_clients(self, pilots, controllers):
        config = self.load_config()
        found_cids = defaultdict(list)
        for client in pilots + controllers:
            cid = int(client["cid"])
            if cid in config:
                found_cids[cid].append(client)
        return dict(found_cids)

    def get_display_name(self, key, client_data):
        config = self.load_config()
        return config.get(key, str(key))

    def get_offline_description(self, key):
        config = self.load_config()
        name = config.get(key, str(key))
        return f"{name} went offline", f"CID {key} is no longer connected to the network."

    @tasks.loop(seconds=15)
    async def monitor_loop(self):
        await self.run_monitor_cycle()

    @monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(VATSIMMonitor(bot))
