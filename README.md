# VATSIM Watchlist Bot (Public Fork)

This repository contains a Discord bot that monitors VATSIM data and provides useful alerts and utilities for controllers and pilots. This is a cleaned, public-friendly fork intended for easy deployment and customization.

## Features
- VATSIM data monitoring and notifications
- CID/callsign/type monitors with persistent JSON-backed state
- P56 monitor support (local API integration)
- Moderation / CoC tools (optional)

This fork removes personal or private features (personal karma, owner-specific shortcuts, voice/WWV audio features) and replaces private IDs with configurable environment variables.

## Requirements
- Python 3.9+
- `pip` to install dependencies

## Installation
1. Clone the repository:

```powershell
git clone https://github.com/youruser/vatsim-watchlist-bot.git
cd vatsim-watchlist-bot
```

2. Create and activate a virtual environment, then install requirements:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Configure environment variables. Create a `.env` file in the repo root or set these in your environment. Minimal recommended variables:

- `DISCORD_TOKEN` (required) - your bot token
- `ADMIN_ID` (optional) - numeric Discord user id allowed to run admin-only commands
- `CHANNEL_ID` (optional) - channel id used for forwarded DMs
- `VATUSA_TOKEN`, `MAPBOX_TOKEN`, `OPENCAGE_KEY`, etc. (optional) - API keys for features

Example `.env`:

```
DISCORD_TOKEN=bot_token_here
ADMIN_ID=123456789012345678
CHANNEL_ID=987654321098765432
```

## Running
Run the bot with:

```powershell
python bot.py
```

The bot will load the included `extensions/` modules by default. To change which extensions are loaded, edit `bot.py`.

## Making the Bot Public-Friendly
- Personal/custom modules and features have been removed from defaults (karma, WWV, voice modules).
- Admin-only commands check for `ADMIN_ID`. Set this env var to enable administrative control.

## Admin / Auto-update
- The bot includes an admin extension (`extensions.admin_install`) that can install single-file extensions remotely and admin commands for `update`, `restart`, `shutdown`, `loadext`, and `unloadext`.
- To enable admin commands, set `ADMIN_ID` to your Discord user id in the `.env` file. Admin commands will refuse to run if `ADMIN_ID` is unset or `0`.

Usage examples (on Discord):

- Update from GitHub and optionally install requirements: `!update`
- Restart the bot after an update: `!restart`
- Load an extension at runtime: `!loadext extensions.my_extension`
- Install a single-file extension from raw GitHub (admin-only): `!installext https://raw.githubusercontent.com/user/repo/main/extensions/myext.py`

## Disabling Optional Features
- Some extensions expect API keys (Mapbox, VATUSA). If you don't set those environment variables, the corresponding commands will be disabled or return an error message.

## Pruning Unused Dependencies
- This public fork removes audio/voice features from the default load list; `PyNaCl` and `pydub` were removed from `requirements.txt`. If you add voice/audio modules later, re-add the appropriate packages.

## Troubleshooting
- If the bot refuses to start, check `DISCORD_TOKEN` and that the Python version is compatible (3.9+).
- To run in a systemd service, see `docs/deploy_rpi.md` for an example systemd unit and post-merge hook.

## Commands (built-in)
Below is a summary of the bot's built-in commands, grouped by extension. Use these from any channel the bot can read (prefix is `!` by default).

- **Core / Admin**
	- `!dm @User <message>`: Forward a message (sends a DM to the target user containing your message).
	- `!update` (admin-only): Pull latest code from the git remote and attempt to install updated requirements.
	- `!restart` (admin-only): Pull latest code, install requirements, and restart the bot.
	- `!shutdown` (admin-only): Save state and shut down the bot.
	- `!loadext <module.path>` (admin-only): Load an extension at runtime, e.g. `!loadext extensions.myext`.
	- `!unloadext <module.path>` (admin-only): Unload an extension at runtime.
	- `!installext <url>` (admin-only, Administrator permission): Download a single `.py` extension and install it into `extensions/`.

- **VATSIM commands (`extensions/vatsim.py`)**
	- `!cid <CID>`: Show VATSIM member info for a CID.
	- `!usa <CID>`: Show VATUSA profile info for a CID.
	- `!lname <lastname> [page]`: Search VATUSA users by last name (paged results).
	- `!atis <ICAO>`: Get ATIS entries for an airport.
	- `!sup`: List online VATSIM supervisors.
	- `!status <CID>`: Check if a CID is currently online on VATSIM and show status.
	- `!stats <CID>`: Get VATSIM statistics for a CID.
	- `!callsign <CALLSIGN>`: Lookup a connected callsign and show location/status.
	- `!com <CALLSIGN>`: Get frequencies associated with a callsign.
	- `!faclist`: List all VATUSA facilities.
	- `!facinfo <FACILITY>`: Get detailed info for a facility (e.g. `ZDC`).
	- `!facroster <FACILITY> [home/visit/both]`: Show facility roster.
	- `!metar <ICAO>`: Fetch METAR for an airport.

- **Code-of-Conduct / Monitoring (`extensions/coc_monitor.py`)**
	- `!cocmonitor [on|off]`: Toggle CoC real-time monitoring.
	- `!cocreset`: Reset the CoC alert cache.
	- `!a4check`: Check for suspected CoC A4 name violations.
	- `!fakename [add|remove|list] [pattern]`: Manage fake-name detection patterns.
	- `!a1mon [add|remove|list] [keyword]`: Manage A1 keyword monitoring.
	- `!a4mon [mute|unmute|status]`: Toggle A4 violation alerts.
	- `!p56mon [mute|unmute|status]`: Toggle P56 intrusion alerts.
	- `!p56 [limit]`: Show recent P56 intrusion events (limit defaults to 10).
	- `!a9mon [add|remove|list] [keyword]`: Manage A9 keyword monitoring.

- **FAA / Advisories (`extensions/faa_adv_monitor.py`, `extensions/faa_restrictions.py`)**
	- `!faaadv [new] [limit]`: Fetch FAA advisories. `new` shows only unseen advisories; `limit` controls how many to post.
	- `!faares [REQUESTING] [PROVIDING]`: Fetch compact FAA restriction entries (defaults to ALL/ALL).
	- `!faaresmon [REQUESTING] [PROVIDING]` / `!faaresmon STOP`: Start or stop a per-minute FAA restrictions monitor.

- **New CID Monitor (`extensions/newcid_monitor.py`)**
	- `!newcid [mute|unmute|status]`: Show highest CID tracked and toggle alerts.
	- `!resetcid` (admin): Reset the highest CID tracker.

- **System / Host (`extensions/system_stats.py`)**
	- `!sys` (aliases: `!piusage`, `!sysstats`, `!sysinfo`): Show CPU, memory, disk, network, uptime and top processes (requires `psutil`).

If a command is admin-only, the bot will reply that you are unauthorized unless your user id matches `ADMIN_ID` or you have the necessary Discord permissions (as documented for `!installext`).

If you'd like I can generate a markdown-formatted `!help` output that matches the bot's built-in `!help` command and add it as `docs/commands.md` for easy browsing.

## Contributing
If you add new extensions, place them in `extensions/` and add them to the `extensions` list in `bot.py` if you want them loaded by default.

## License
This fork is provided as-is for public use. Please add a license file if you intend to publish it on GitHub.
