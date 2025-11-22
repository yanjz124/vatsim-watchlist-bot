from datetime import datetime
from dateutil import parser


def format_date(iso_string):
    if not iso_string:
        return "N/A"
    try:
        return datetime.fromisoformat(iso_string.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except Exception:
        return iso_string  # fallback


def format_time(iso_str):
    try:
        return parser.isoparse(iso_str).strftime("%Y-%m-%d %H:%MZ")
    except Exception:
        return iso_str or "N/A"
