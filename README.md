# VATSIM Watchlist Bot

This repository contains a Discord bot that monitors VATSIM data and provides useful alerts and utilities for controllers and pilots. It is designed to be configurable and easy to deploy.

One bot instance can serve many Discord servers. Each server picks its own
alert channel, keeps its own watchlists, and opts into whichever network-wide
feeds it wants — nothing is shared between servers.

## Features
- VATSIM data monitoring and notifications
- CID/callsign/type monitors with persistent JSON-backed state, scoped per server
- Position embeds with a live map trail coloured by altitude
- Real-world ATIS change alerts, FAA advisories, controller workload alerts
- Code-of-Conduct keyword and name-convention monitoring
- Moderation / CoC tools (optional)

## Adding the bot to a server

Invite it, then tell it where to talk:

1. **`/setchannel #your-channel`** — the channel alerts post to. Nothing posts
   until this is set. Requires the **Manage Server** permission.
2. **`/feeds`** — subscribe to network-wide feeds. All of them are **off by
   default**, so a fresh invite never floods a server.
3. **`!cidmon add <CID>`**, **`!csmon add <CALLSIGN>`**, **`!typemon add <TYPE>`** —
   build the server's watchlist. Watchlists need no subscription: a server with
   an empty watchlist is silent, and one with entries gets alerts for exactly
   those entries.

`/config` shows the current channel and feed settings. `!invite` generates an
invite link for the running bot with the right permissions preselected.

### Watchlists vs. global feeds

Two different things share the word "monitor":

| | Scope | Opt-in |
|---|---|---|
| **Watchlists** (`!cidmon`, `!csmon`, `!typemon`) | Only the CIDs / callsigns / types that server added | None needed — empty list means silent |
| **Global feeds** (`faa`, `newcid`, `atis`, `workload`, `coc`) | Network-wide, identical for every server | `/feeds`, default off |

Per-server settings live in `data/guild_config.json`; watchlists live in the
other `data/*.json` files keyed by guild id.

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

## Creating a Discord Bot (quick start)
1. Go to the Discord Developer Portal: https://discord.com/developers/applications and create a new Application.
2. In the application page open the **Bot** tab and click **Add Bot**. Under the **Token** section click **Reset Token** (or **Copy**) and save the token — this becomes your `DISCORD_TOKEN`.
3. Under **OAuth2 → URL Generator** select **both** the `bot` and
   `applications.commands` scopes — the second one is required for
   `/setchannel`, `/config` and `/feeds` to appear. In **Bot Permissions**
   choose the permissions below, then copy the generated invite URL.

If the bot is already running, `!invite` produces the same URL for you.

## Permissions & Intents

Required permissions:

| Permission | Why |
|---|---|
| View Channels | See the alert channel |
| Send Messages | Post alerts |
| Embed Links | Every alert is an embed |
| Attach Files | Position maps are uploaded as images |
| Read Message History | Edit an existing alert in place instead of reposting |

`/setchannel` verifies Send Messages and Embed Links before accepting a
channel, and warns if Attach Files is missing (maps silently won't render).

### Privileged intents

The bot requests exactly one privileged intent: **Message Content**, needed
for the `!` prefix commands. Enable it under **Bot → Privileged Gateway
Intents** in the Developer Portal. It does *not* need Server Members or
Presence.

Discord requires bots in **100+ servers** to be verified before privileged
intents keep working. Below that threshold no verification is needed. If you
ever cross it and would rather not verify, the prefix commands would have to
move to slash commands and `intents.message_content` can then be dropped.

- How to get your numeric Discord user id (for `ADMIN_ID`): enable Developer Mode in Discord (Appearance → Advanced → Developer Mode), then right-click your username in a server or the members list and choose **Copy ID**.

## Hosting & Running
Basic local run (Linux/macOS):

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# set environment variables (or create a .env file)
python bot.py
```

Basic local run (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python bot.py
```

Systemd (example): copy `systemd/vatsim-watchlist-bot.service.example` to `/etc/systemd/system/vatsim-watchlist-bot.service`, edit `User`, `WorkingDirectory`, and `ExecStart` to point at your install path and python interpreter (virtualenv), then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable vatsim-watchlist-bot.service
sudo systemctl start vatsim-watchlist-bot.service
sudo journalctl -u vatsim-watchlist-bot.service -f
```

Logging & troubleshooting:
- Check `systemctl status vatsim-watchlist-bot.service` and `journalctl -u vatsim-watchlist-bot.service` for runtime errors.
- Ensure `DISCORD_TOKEN` is correct and that required API keys (Mapbox, VATUSA, etc.) are set if you use related features.

Advanced: you can run the bot inside a Docker container or supervise it with process managers (supervisord, pm2). The simplest approach is systemd for Linux hosts.

## Customization
- Owner-only commands (`!update`, `!restart`, `!shutdown`, `!loadext`) check
  `ADMIN_ID`, the bot owner's Discord user id. These are global, not per-server.
- Per-server settings (`/setchannel`, `/feeds`) require the **Manage Server**
  permission in that server — server admins configure their own server without
  needing to be the bot owner.
- `CHANNEL_ID` is legacy and optional. It exists so an install that predates
  multi-guild support keeps working: on first start, if it is set and no server
  has been configured yet, the owning server adopts it and existing watchlist
  files are migrated into it. Leave it unset on a fresh deployment.

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

- **Monitors**
	- **Callsign Monitor (`extensions/callsign_monitor.py`)**
		- `!csmon`: Show usage for callsign monitoring (group command).
		- `!csmon add <RULE> <NAME(optional)>`: Add a callsign rule (e.g., `CXK*`).
		- `!csmon remove <RULE>`: Remove a monitored callsign rule.
		- `!csmon list`: List currently monitored callsign rules (paged).
		- `!csmute`: List active callsign mutes.
		- `!csmute <PATTERN> [HOURS]`: Mute alerts for matching callsigns (default 24h, `0` = permanent).
		- `!csmute -<PATTERN>`: Unmute (leading `-`).

	- **Type Monitor (`extensions/type_monitor.py`)**
		- `!typemon`: Show usage for aircraft type monitoring (group command).
		- `!typemon add <PATTERN> <NAME(optional)>`: Add an aircraft type pattern (e.g., `B738`, `A320*`).
		- `!typemon remove <PATTERN>`: Remove an aircraft type pattern.
		- `!typemon list`: List currently monitored aircraft types (paged).

	- **CID Monitor (`extensions/cid_monitor.py`)**
		- `!cidmon`: Show usage for CID monitoring (group command).
		- `!cidmon add <CID1> name1(optional), <CID2> name2(optional),...`: Add one or more CIDs to monitor.
		- `!cidmon remove <CID>`: Remove a CID from monitoring.
		- `!cidmon list`: List currently monitored CIDs (paged).

- **Code-of-Conduct / Monitoring (`extensions/coc_monitor.py`)**
	- `!cocmonitor [on|off]`: Toggle CoC real-time monitoring.
	- `!cocreset`: Reset the CoC alert cache.
	- `!a4check`: Check for suspected CoC A4 name violations.
	- `!fakename [add|remove|list] [pattern]`: Manage fake-name detection patterns.
	- `!a1mon [add|remove|list] [keyword]`: Manage A1 keyword monitoring.
	- `!a4mon [mute|unmute|status]`: Toggle A4 violation alerts.
	- `!a9mon [add|remove|list] [keyword]`: Manage A9 keyword monitoring.

- **FAA / Advisories (`extensions/faa_adv_monitor.py`, `extensions/faa_restrictions.py`)**
	- `!faaadv [new] [limit]`: Fetch FAA advisories. `new` shows only unseen advisories; `limit` controls how many to post.
	- `!faaadv [mute|unmute|status]`: Manage automatic FAA advisory auto-posting. By default automatic FAA postings are **muted**; use `!faaadv unmute` to enable posting. `!faaadv status` shows current state.
	- `!faares [REQUESTING] [PROVIDING]`: Fetch compact FAA restriction entries (defaults to ALL/ALL).
	- `!faaresmon [REQUESTING] [PROVIDING]` / `!faaresmon STOP`: Start or stop a per-minute FAA restrictions monitor.

- **New CID Monitor (`extensions/newcid_monitor.py`)**
	- `!newcid [mute|unmute|status]`: Show highest CID tracked and toggle alerts.
	- `!resetcid` (admin): Reset the highest CID tracker.

- **System / Host (`extensions/system_stats.py`)**
	- `!sys` (aliases: `!piusage`, `!sysstats`, `!sysinfo`): Show CPU, memory, disk, network, uptime and top processes (requires `psutil`).

If a command is admin-only, the bot will reply that you are unauthorized unless your user id matches `ADMIN_ID` or you have the necessary Discord permissions (as documented for `!installext`).

Note on defaults and persistence:
- The FAA automatic advisory poster and the CoC A4 real-time alerts are **muted by default** on first run to avoid unexpected spam in a server. Use `!faaadv unmute` to enable FAA auto-posting and `!a4mon unmute` to enable A4 violation alerts.
- Mute/unmute changes for FAA (`!faaadv`) and A4 (`!a4mon`) are persisted to disk so the chosen state survives restarts.

If you'd like I can generate a markdown-formatted `!help` output that matches the bot's built-in `!help` command and add it as `docs/commands.md` for easy browsing.

## Contributing
If you add new extensions, place them in `extensions/` and add them to the `extensions` list in `bot.py` if you want them loaded by default.

## License
This repository is provided as-is. See `LICENSE` for licensing information.
