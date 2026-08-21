# Commands Reference

This document lists the bot's built-in commands, grouped by extension. Use the `!` prefix (default) in any channel the bot can read.

Two levels of permission appear below:

- **(owner-only)** — checked against `ADMIN_ID`, the bot owner. Global.
- **(Manage Server)** — checked against the caller's permission in the server
  they're calling from. Server admins configure their own server.

Watchlists and settings are per server: `!cidmon add` in one server has no
effect in another.

## Server setup (`extensions/guild_setup.py`)

Available as slash commands so they're discoverable right after an invite;
each also works with the `!` prefix.

- `/setchannel [#channel]` or `!setchannel [#channel]` (Manage Server)
  - Choose where this server's alerts post. Defaults to the current channel.
    Nothing posts until this is set. Verifies the bot can send messages and
    embed links there.
- `/config` or `!config`
  - Show this server's alert channel and which global feeds are on.
- `/feeds [feed] [on|off]` or `!feeds [<feed> on|off]` (Manage Server to change)
  - Subscribe this server to a network-wide feed. Feeds: `faa`, `newcid`,
    `atis`, `workload`, `coc`. All default to **off**. With no arguments,
    shows the same panel as `/config`.
- `!invite`
  - Generate an invite link for this bot with the required permissions.

## Core / Admin
- `!dm @User <message>`
  - Send a DM to a user with your message. Usage: `!dm @User Hello there`.
- `!update` (owner-only)
  - Pulls the latest code from the git remote and attempts to install any updated requirements.
- `!restart` (owner-only)
  - Pulls, installs requirements, and restarts the bot.
- `!shutdown` (owner-only)
  - Save state and shut down the bot.
- `!loadext <module.path>` (owner-only)
  - Load an extension at runtime, e.g. `!loadext extensions.myext`.
- `!unloadext <module.path>` (owner-only)
  - Unload an extension at runtime.
- `!installext <url>` (owner-only, Admin permission required)
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
- `!a9mon [add|remove|list] [keyword]`
  - Manage A9 keyword monitoring.

## FAA / Advisories (`extensions/faa_adv_monitor.py`, `extensions/faa_restrictions.py`)
- `!faaadv [new] [limit]`
  - Fetch FAA advisories. `new` shows only unseen advisories; `limit` controls how many to post.
- `!faaadv [mute|unmute|status]`
  - Toggle automatic FAA advisory posting for this server. Equivalent to
    `/feeds feed:faa`.
- `!faares [REQUESTING] [PROVIDING]`
  - Fetch compact FAA restriction entries (defaults to ALL/ALL).
- `!faaresmon [REQUESTING] [PROVIDING]` / `!faaresmon STOP`
  - Start or stop a per-minute FAA restrictions monitor.

## New CID Monitor (`extensions/newcid_monitor.py`)
- `!newcid [mute|unmute|status]`
  - Show highest CID tracked and toggle alerts.
- `!resetcid` (admin)
  - Reset the highest CID tracker.

## Watchlists (`cid_monitor.py`, `callsign_monitor.py`, `type_monitor.py`)
Each server keeps its own lists; these need no feed subscription.

- `!cidmon [add|remove|list] <CID> [name]`
  - Watch specific VATSIM CIDs.
- `!csmon [add|remove|list] <RULE> [name]`
  - Watch callsign patterns, `*` wildcards allowed (e.g. `CXK*`).
- `!csmute`
  - List this server's active callsign mutes.
- `!csmute <PATTERN> [hours]`
  - Suppress alerts for callsigns matching `PATTERN` (`*` wildcards allowed)
    without removing the monitor rule. Defaults to 24 hours; `0` or negative
    makes it permanent. Expired mutes are pruned automatically.
- `!csmute -<PATTERN>`
  - Unmute (note the leading `-`).
- `!typemon [add|remove|list] <PATTERN> [name]`
  - Watch aircraft types (e.g. `B738`, `A320*`). Pilots only.

## Workload (`extensions/workload.py`)
- `!wl [filter]`
  - Show current controller workload (pilots per controller).
- `!wlmon [on|off|<number>]`
  - Toggle workload alerts for this server, or set the pilot-count threshold.
    Also needs the `workload` feed enabled via `/feeds`.
- `!wlstats [all|cs [prefix]|<prefix>|clear]`
  - Statistics on which controllers have tripped the workload alert: trigger
    counts, peak pilot count, and first/last trigger times. `cs` groups by
    callsign across CIDs; `clear` wipes this server's recorded stats.

## System / Host (`extensions/system_stats.py`)
- `!sys` (aliases: `!piusage`, `!sysstats`, `!sysinfo`)
  - Show CPU, memory, disk, network, uptime and top processes (requires `psutil`).

---

If you want a machine-readable or more detailed version (with parameter descriptions and examples), tell me which commands you want expanded and I will add examples per-command.
