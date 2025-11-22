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

## Contributing
If you add new extensions, place them in `extensions/` and add them to the `extensions` list in `bot.py` if you want them loaded by default.

## License
This fork is provided as-is for public use. Please add a license file if you intend to publish it on GitHub.
