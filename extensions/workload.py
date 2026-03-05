# extensions/workload.py

import math
import asyncio

import aiohttp
import discord
from discord.ext import commands, tasks
from discord.utils import utcnow

from config import CHANNEL_ID, atc_rating
from utils.data_manager import load_workload_monitor, save_workload_monitor
from utils.transceivers_cache import get_transceivers_data
from utils.vatsim_datafeed import fetch_vatsim_data

VNAS_CONTROLLERS_URL = "https://live.env.vnas.vatsim.net/data-feed/controllers.json"

# OBS positions are excluded from results entirely.
_EXCLUDED_SUFFIXES = {"OBS"}

# Frequencies excluded from counting/display — every client monitors these
# universally so they inflate workload numbers.  Matched by formatted MHz
# string (e.g. "121.500") rather than exact Hz to catch slight offsets in
# the AFV data (e.g. 121499975 Hz still displays as "121.500").
_IGNORED_FREQ_MHZ: frozenset[str] = frozenset({"121.500", "243.000"})


def _is_ignored_freq(freq_hz: int) -> bool:
    return f"{freq_hz / 1_000_000:.3f}" in _IGNORED_FREQ_MHZ

DEFAULT_THRESHOLD = 15
MONITOR_INTERVAL = 60
ESCALATION_STEP = 5   # alert again each time count climbs this many above threshold


# ── helpers ───────────────────────────────────────────────────────────────────

def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _radio_range_nm(height_msl_m: float) -> float:
    h_ft = max(height_msl_m, 0.0) * 3.28084
    return max(5.0, 1.23 * math.sqrt(h_ft))


def _normalize_freq(raw) -> str:
    if raw is None:
        return "N/A"
    try:
        v = float(raw)
        if v > 1_000_000:
            v /= 1_000_000
        return f"{v:.3f}"
    except (ValueError, TypeError):
        return str(raw)


def _suffix(callsign: str) -> str:
    return callsign.rsplit("_", 1)[-1].upper() if "_" in callsign else callsign.upper()


def _is_excluded(callsign: str) -> bool:
    return _suffix(callsign) in _EXCLUDED_SUFFIXES


async def _fetch_vnas_controllers() -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                VNAS_CONTROLLERS_URL,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                print(f"[Workload] vNAS feed returned HTTP {resp.status}")
    except Exception as e:
        print(f"[Workload] vNAS fetch error: {e}")
    return []


# ── core data fetch ───────────────────────────────────────────────────────────

async def fetch_workload_data() -> list:
    vnas_list, trans_data, vatsim_data = await asyncio.gather(
        _fetch_vnas_controllers(),
        get_transceivers_data(),
        fetch_vatsim_data(),
    )

    if not vnas_list:
        return []

    # Build VATSIM controller lookup: callsign.upper() -> {cid, name, rating}
    vatsim_ctrl_lookup: dict[str, dict] = {}
    if vatsim_data:
        for ctrl in vatsim_data.get("controllers", []):
            cs = ctrl.get("callsign", "").upper()
            vatsim_ctrl_lookup[cs] = {
                "cid": ctrl.get("cid", "N/A"),
                "name": ctrl.get("name", "N/A"),
                "rating": atc_rating.get(ctrl.get("rating", 0), "N/A"),
            }

    # Build lookup: callsign.upper() -> list of {freq_hz, lat, lon, height_m}
    trans_lookup: dict[str, list] = {}
    for entry in trans_data:
        cs = entry.get("callsign", "").upper()
        trans = []
        for t in entry.get("transceivers", []):
            lat = t.get("latDeg")
            lon = t.get("lonDeg")
            freq = t.get("frequency")
            if lat is not None and lon is not None and freq is not None:
                trans.append({
                    "freq_hz": int(freq),
                    "lat": float(lat),
                    "lon": float(lon),
                    "height_m": float(t.get("heightMslM", 0.0)),
                })
        if trans:
            trans_lookup[cs] = trans

    raw_controllers = vnas_list.get("controllers", []) if isinstance(vnas_list, dict) else vnas_list

    seen_callsigns: set[str] = set()
    active_positions: list[dict] = []
    for ctrl in raw_controllers:
        if isinstance(ctrl, str):
            cs = ctrl.upper().strip()
            if cs and cs not in seen_callsigns:
                seen_callsigns.add(cs)
                active_positions.append({"callsign": cs, "freq_hz": None})
            continue
        for pos in ctrl.get("positions", []):
            if not pos.get("isActive", False):
                continue
            cs = (pos.get("defaultCallsign") or pos.get("callsign") or "").upper().strip()
            if not cs or cs in seen_callsigns:
                continue
            seen_callsigns.add(cs)
            active_positions.append({"callsign": cs, "freq_hz": pos.get("frequency")})

    results = []
    for pos in active_positions:
        callsign = pos["callsign"]
        feed_freq_hz = pos["freq_hz"]

        if _is_excluded(callsign):
            continue

        vinfo = vatsim_ctrl_lookup.get(callsign, {})
        ctrl_trans = trans_lookup.get(callsign)

        if not ctrl_trans:
            freq_str = f"{feed_freq_hz / 1_000_000:.3f}" if feed_freq_hz else "N/A"
            results.append({"callsign": callsign, "frequency": freq_str, "pilot_count": 0, **vinfo})
            continue

        primary_mhz = (
            f"{feed_freq_hz / 1_000_000:.3f}"
            if feed_freq_hz and not _is_ignored_freq(feed_freq_hz)
            else None
        )

        all_freqs = {t["freq_hz"] for t in ctrl_trans if not _is_ignored_freq(t["freq_hz"])}

        if not all_freqs and not primary_mhz:
            results.append({"callsign": callsign, "frequency": "N/A", "pilot_count": 0, **vinfo})
            continue

        all_mhz_set: set[str] = {f"{f / 1_000_000:.3f}" for f in all_freqs}
        if primary_mhz and primary_mhz in all_mhz_set:
            rest = sorted(all_mhz_set - {primary_mhz})
            freq_str = primary_mhz + (" / " + " / ".join(rest) if rest else "")
        elif primary_mhz:
            freq_str = primary_mhz
        else:
            freq_str = " / ".join(sorted(all_mhz_set))

        if primary_mhz:
            primary_trans = [
                t for t in ctrl_trans
                if f"{t['freq_hz'] / 1_000_000:.3f}" == primary_mhz
            ]
            primary_freq_set = {t["freq_hz"] for t in primary_trans}
        else:
            primary_trans = [t for t in ctrl_trans if t["freq_hz"] in all_freqs]
            primary_freq_set = all_freqs

        count = sum(
            1
            for other_cs, other_trans in trans_lookup.items()
            if other_cs != callsign
            and any(
                ot["freq_hz"] in primary_freq_set
                and _haversine_nm(ct["lat"], ct["lon"], ot["lat"], ot["lon"])
                    <= _radio_range_nm(ct["height_m"])
                for ct in primary_trans
                for ot in other_trans
            )
        )

        results.append({"callsign": callsign, "frequency": freq_str, "pilot_count": count, **vinfo})

    results.sort(key=lambda x: x["pilot_count"], reverse=True)
    return results


# ── embed builders ────────────────────────────────────────────────────────────

def _table_embeds(controllers: list, threshold: int, *, filter_label: str | None = None) -> list[discord.Embed]:
    title = "vNAS Controller Workload"

    if not controllers:
        desc = "No matching controllers found." if filter_label else "No vNAS controllers currently online."
        return [discord.Embed(
            title=title,
            description=desc,
            color=discord.Color.greyple(),
            timestamp=utcnow(),
        )]

    any_high = any(c["pilot_count"] >= threshold for c in controllers)
    color = discord.Color.red() if any_high else discord.Color.blue()

    footer_parts = [f"Threshold: {threshold}"]
    if filter_label:
        footer_parts.append(filter_label)
    footer_text = " | ".join(footer_parts)

    ROWS_PER_EMBED = 25
    total_pages = (len(controllers) + ROWS_PER_EMBED - 1) // ROWS_PER_EMBED
    embeds: list[discord.Embed] = []

    for page, i in enumerate(range(0, len(controllers), ROWS_PER_EMBED), start=1):
        chunk = controllers[i: i + ROWS_PER_EMBED]
        page_title = title if total_pages == 1 else f"{title} ({page}/{total_pages})"

        e = discord.Embed(title=page_title, color=color, timestamp=utcnow())

        for c in chunk:
            count = c["pilot_count"]
            cid = c.get("cid", "N/A")
            name = c.get("name", "N/A")
            rating = c.get("rating", "N/A")
            field_name = c["callsign"]
            field_value = (
                f"{c['frequency']} · {count} aircraft\n"
                f"{name} ({cid}) · {rating}"
            )
            e.add_field(name=field_name, value=field_value, inline=False)

        e.set_footer(text=footer_text)
        embeds.append(e)

    return embeds


# ── cog ───────────────────────────────────────────────────────────────────────

class WorkloadMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        state = load_workload_monitor()
        self.monitor_enabled = state['enabled']
        self.threshold = state['threshold']
        self._alerted_band: dict[str, int] = {}
        self.monitor_loop.start()

    async def cog_unload(self):
        self.monitor_loop.cancel()

    # ── monitor loop ──────────────────────────────────────────────────────────

    @tasks.loop(seconds=MONITOR_INTERVAL)
    async def monitor_loop(self):
        if not self.monitor_enabled:
            return

        try:
            controllers = await fetch_workload_data()
        except Exception as e:
            print(f"[Workload Monitor] Error: {e}")
            return

        above_cs = {c["callsign"] for c in controllers if c["pilot_count"] >= self.threshold}
        for cs in list(self._alerted_band):
            if cs not in above_cs:
                del self._alerted_band[cs]

        channel = self.bot.get_channel(CHANNEL_ID)
        if not channel:
            return

        to_alert = []
        for c in controllers:
            if c["pilot_count"] < self.threshold:
                continue
            band = (c["pilot_count"] - self.threshold) // ESCALATION_STEP
            if band > self._alerted_band.get(c["callsign"], -1):
                self._alerted_band[c["callsign"]] = band
                to_alert.append(c)

        if not to_alert:
            return

        for embed in _table_embeds(to_alert, self.threshold):
            await channel.send(embed=embed)

    @monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    # ── commands ──────────────────────────────────────────────────────────────

    @commands.command(name="wl", aliases=["workload"])
    async def wl_cmd(self, ctx, *, arg: str = ""):
        """
        Show current vNAS controller workload.
        Usage:
          !wl           — positions at or above threshold-5
          !wl all       — show every position
          !wl <prefix>  — show positions matching prefix (e.g. !wl ATL)
        """
        msg = await ctx.send("Fetching workload data...")
        try:
            controllers = await fetch_workload_data()
        except Exception as e:
            await msg.edit(content=f"Error fetching workload data: {e}")
            return

        arg = arg.strip()
        filter_label = None

        if arg.lower() == "all" or arg == "":
            if arg == "":
                cutoff = self.threshold - 5
                controllers = [c for c in controllers if c["pilot_count"] >= cutoff]
                filter_label = f"showing >= {cutoff} pilots"
        else:
            prefix = arg.upper()
            controllers = [
                c for c in controllers
                if c["callsign"].upper().startswith(prefix + "_")
                or c["callsign"].upper() == prefix
            ]
            filter_label = f"filter: {prefix}"

        await msg.delete()
        for embed in _table_embeds(controllers, self.threshold, filter_label=filter_label):
            await ctx.send(embed=embed)

    @commands.command(name="wlmon")
    async def wlmon_cmd(self, ctx, arg: str = ""):
        """
        Control the workload monitor.
        Usage:
          !wlmon           — show status
          !wlmon on/off    — enable/disable monitor
          !wlmon <number>  — set pilot-count alert threshold (e.g. !wlmon 20)
        """
        if not arg:
            status = "enabled" if self.monitor_enabled else "disabled"
            embed = discord.Embed(
                title="Workload Monitor Status",
                color=discord.Color.green() if self.monitor_enabled else discord.Color.greyple(),
            )
            embed.add_field(name="Status", value=status.capitalize(), inline=True)
            embed.add_field(name="Threshold", value=f"{self.threshold} pilots", inline=True)
            embed.add_field(name="Escalation", value=f"every +{ESCALATION_STEP}", inline=True)
            embed.add_field(
                name="Alert logic",
                value=(
                    f"Fires when a controller first crosses **{self.threshold}** pilots, "
                    f"then again each time the count climbs another **{ESCALATION_STEP}** "
                    f"(i.e. {self.threshold}, {self.threshold + ESCALATION_STEP}, "
                    f"{self.threshold + ESCALATION_STEP * 2}, ...). "
                    f"Resets if the count drops below **{self.threshold}**."
                ),
                inline=False,
            )
            embed.add_field(
                name="Commands",
                value=(
                    "`!wlmon on/off` — enable/disable\n"
                    "`!wlmon <number>` — set threshold (e.g. `!wlmon 20`)"
                ),
                inline=False,
            )
            await ctx.send(embed=embed)
            return

        lower = arg.lower()

        if lower == "on":
            self.monitor_enabled = True
            save_workload_monitor(self.monitor_enabled, self.threshold)
            await ctx.send(
                f"Workload monitor **enabled**. Threshold: **{self.threshold}** pilots."
            )
        elif lower == "off":
            self.monitor_enabled = False
            save_workload_monitor(self.monitor_enabled, self.threshold)
            await ctx.send("Workload monitor **disabled**.")
        else:
            try:
                n = int(arg)
                if n < 1:
                    await ctx.send("Threshold must be at least 1.")
                    return
                self.threshold = n
                self._alerted_band.clear()
                save_workload_monitor(self.monitor_enabled, self.threshold)
                await ctx.send(f"Workload alert threshold set to **{n}** pilots.")
            except ValueError:
                await ctx.send(
                    f"Unknown argument `{arg}`. Use `on`, `off`, or a number for threshold."
                )


async def setup(bot):
    await bot.add_cog(WorkloadMonitor(bot))
