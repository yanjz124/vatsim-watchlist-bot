import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
VATUSA_API_KEY = os.getenv("VATUSA_TOKEN")
AVIATIONSTACK_KEY = os.getenv("AVIATIONSTACK_KEY")
MAPBOX = os.getenv("MAPBOX_TOKEN")
OPENCAGE_KEY = os.getenv("OPENCAGE_KEY")
# Optional numeric IDs. Use environment variables if you need them; default to 0 (unset).
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ROLE_ID = int(os.getenv("ROLE_ID", "0"))
# Admin/owner id for admin-only commands. Set to 0 to disable admin-only restrictions.
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

# P56 Monitor API endpoint (local service on Pi)
P56_API_URL = os.getenv("P56_API_URL", "http://127.0.0.1:8000/api/v1/p56/")
