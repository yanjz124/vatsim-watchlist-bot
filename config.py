import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
VATUSA_API_KEY = os.getenv("VATUSA_TOKEN")
AVIATIONSTACK_KEY = os.getenv("AVIATIONSTACK_KEY")
MAPBOX = os.getenv("MAPBOX_TOKEN")
OPENCAGE_KEY = os.getenv("OPENCAGE_KEY")
# CHANNEL_ID is legacy and optional. Alert channels are now configured per
# server with /setchannel and stored in data/guild_config.json. This is only
# read once at startup: if it is set and no guild has been configured yet, the
# owning guild adopts it and any pre-multi-guild data files are migrated into
# it, so an existing single-server install keeps working untouched. Leave it
# at 0 on a fresh deployment.
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ROLE_ID = int(os.getenv("ROLE_ID", "0"))
# Bot owner's Discord user id. Gates the commands that control the bot
# process itself: !update, !restart, !restartlinux, !shutdown, !loadext,
# !unloadext, !installext. Global, not per-server.
# Leaving it at 0 does NOT open those commands -- the check is
# `author.id != ADMIN_ID`, so an unset value denies everyone. That is the
# intended failure mode: an unconfigured bot is locked, not wide open.
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

atc_rating = {
    -1: 'INA', 0: 'SUS', 1: 'OBS', 2: 'S1', 3: 'S2', 4: 'S3', 5: 'C1', 6: 'C2', 7: 'C3',
    8: 'I1', 9: 'I2', 10: 'I3', 11: 'SUP', 12: 'ADM'
}

pilot_rating = {
    -1: 'INA', 0: 'P0', 1: 'PPL', 3: 'IR', 7: 'CMEL', 15: 'ATPL', 31: 'FI', 63: 'FE'
}

military_rating = {
    0: 'M0', 1: 'M1', 3: 'M2', 7: 'M3', 15: 'M4'
}

facility = {
    0: "OBS", 1: "FSS", 2: "DEL", 3: "GND", 4: "TWR", 5: "APP", 6: "CTR"
}

