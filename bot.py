# bot.py
import discord
from discord.ext import commands
from config import DISCORD_TOKEN
import asyncio

intents = discord.Intents.all()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!',
                   intents=intents,
                   case_insensitive=True
                   )

extensions = [
    "extensions.core",
    "extensions.vatsim",
    "extensions.cid_monitor",
    "extensions.cid_monitor_loop",
    "extensions.callsign_monitor",
    "extensions.callsign_monitor_loop",
    "extensions.faa_adv_monitor",
    "extensions.faa_restrictions",
    "extensions.system_stats",
    "extensions.admin_install",
    "extensions.coc_monitor",
    "extensions.coc_monitor_loop",
    "extensions.newcid_monitor",
    "extensions.newcid_monitor_loop",
    "extensions.type_monitor",
    "extensions.type_monitor_loop",
    "extensions.p56_monitor_loop"
]
async def main():
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN is not set in environment variables or config")
    for ext in extensions:
        await bot.load_extension(ext)
    await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

