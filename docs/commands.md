# Commands Reference

This document lists the bot's built-in commands, grouped by extension. Use the `!` prefix (default) in any channel the bot can read.

## Core / Admin
- `!dm @User <message>`
  - Send a DM to a user with your message. Usage: `!dm @User Hello there`.
- `!update` (admin-only)
  - Pulls the latest code from the git remote and attempts to install any updated requirements.
- `!restart` (admin-only)
  - Pulls, installs requirements, and restarts the bot.
- `!shutdown` (admin-only)
  - Save state and shut down the bot.
- `!loadext <module.path>` (admin-only)
  - Load an extension at runtime, e.g. `!loadext extensions.myext`.
- `!unloadext <module.path>` (admin-only)
  - Unload an extension at runtime.
- `!installext <url>` (admin-only, Admin permission required)
  - Download a single `.py` extension from a URL and install it into `extensions/`.

## VATSIM commands (`extensions/vatsim.py`)
- `!cid <CID>`
  - Show VATSIM member info for a CID.
- `!usa <CID>`
  - Show VATUSA profile info for a CID.
- `!lname <lastname> [page]`
  - Search VATUSA users by last name (paged results).
- `!atis <ICAO>`
  - Get ATIS entries for an airport.
- `!sup`
  - List online VATSIM supervisors.
- `!status <CID>`
  - Check whether a CID is online on VATSIM and show status.
- `!stats <CID>`
  - Get VATSIM statistics for a CID.
- `!callsign <CALLSIGN>`
  - Lookup a connected callsign and show location/status.
- `!com <CALLSIGN>`
  - Get frequencies associated with a callsign.
- `!faclist`
  - List all VATUSA facilities.
- `!facinfo <FACILITY>`
  - Get detailed info for a facility (e.g. `ZDC`).
- `!facroster <FACILITY> [home/visit/both]`
  - Show facility roster.
- `!metar <ICAO>`
  - Fetch METAR for an airport.

## Code-of-Conduct / Monitoring (`extensions/coc_monitor.py`)
- `!cocmonitor [on|off]`
  - Toggle CoC real-time monitoring.
- `!cocreset`
  - Reset the CoC alert cache.
- `!a4check`
  - Check for suspected CoC A4 name violations.
- `!fakename [add|remove|list] [pattern]`
  - Manage fake-name detection patterns.
- `!a1mon [add|remove|list] [keyword]`
  - Manage A1 keyword monitoring.
- `!a4mon [mute|unmute|status]`
  - Toggle A4 violation alerts.
- `!p56mon [mute|unmute|status]`
  - Toggle P56 intrusion alerts.
- `!p56 [limit]`
  - Show recent P56 intrusion events (limit defaults to 10).
- `!a9mon [add|remove|list] [keyword]`
  - Manage A9 keyword monitoring.

## FAA / Advisories (`extensions/faa_adv_monitor.py`, `extensions/faa_restrictions.py`)
- `!faaadv [new] [limit]`
  - Fetch FAA advisories. `new` shows only unseen advisories; `limit` controls how many to post.
- `!faares [REQUESTING] [PROVIDING]`
  - Fetch compact FAA restriction entries (defaults to ALL/ALL).
- `!faaresmon [REQUESTING] [PROVIDING]` / `!faaresmon STOP`
  - Start or stop a per-minute FAA restrictions monitor.

## New CID Monitor (`extensions/newcid_monitor.py`)
- `!newcid [mute|unmute|status]`
  - Show highest CID tracked and toggle alerts.
- `!resetcid` (admin)
  - Reset the highest CID tracker.

## System / Host (`extensions/system_stats.py`)
- `!sys` (aliases: `!piusage`, `!sysstats`, `!sysinfo`)
  - Show CPU, memory, disk, network, uptime and top processes (requires `psutil`).

---

If you want a machine-readable or more detailed version (with parameter descriptions and examples), tell me which commands you want expanded and I will add examples per-command.
