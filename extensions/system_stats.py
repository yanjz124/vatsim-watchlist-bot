"""Cog to show system resource usage (CPU, memory, disk, network, uptime, top processes).

Command: !sys (alias: !piusage)

This cog prefers psutil. If psutil is not installed the command will return a helpful message.

Non-blocking: heavy/sync calls are run via asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import datetime
import shutil
import os

import discord
from discord.ext import commands

try:
    import psutil
except Exception:  # pragma: no cover - we want to fail gracefully at runtime
    psutil = None


def _bytes_to_human(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}"
        num /= 1024.0
    return f"{num:.1f}PB"


class SystemStats(commands.Cog):
    """Display system resource usage for the host (Raspberry Pi friendly)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _gather_stats(self) -> dict:
        if psutil is None:
            raise RuntimeError("psutil not installed")

        # Run blocking psutil calls in a thread
        def snapshot():
            s: dict = {}
            s["boot_time"] = psutil.boot_time()  # type: ignore
            s["cpu_percent"] = psutil.cpu_percent(interval=0.5)  # type: ignore
            s["cpu_percpu"] = psutil.cpu_percent(interval=0.0, percpu=True)  # type: ignore
            s["load_avg"] = os.getloadavg() if hasattr(os, "getloadavg") else None
            mem = psutil.virtual_memory()  # type: ignore
            s["mem_total"] = mem.total
            s["mem_used"] = mem.used
            s["mem_percent"] = mem.percent
            s["swap_total"] = psutil.swap_memory().total  # type: ignore
            s["swap_used"] = psutil.swap_memory().used  # type: ignore
            du = shutil.disk_usage("/")
            s["disk_total"] = du.total
            s["disk_used"] = du.used
            # network IO counters (cumulative)
            s["net_io"] = psutil.net_io_counters()  # type: ignore
            # top processes by memory
            procs = []
            for p in psutil.process_iter(["pid", "name", "username", "memory_info", "memory_percent"]):  # type: ignore
                try:
                    info = p.info
                    procs.append(info)
                except Exception:
                    continue
            procs.sort(key=lambda x: x.get("memory_percent") or 0, reverse=True)
            s["top_procs"] = procs[:6]
            return s

        snap1 = await asyncio.to_thread(snapshot)

        # measure network rates over 1 second (non-blocking sleep)
        await asyncio.sleep(1.0)

        def snapshot_net():
            return psutil.net_io_counters()  # type: ignore

        snap2 = await asyncio.to_thread(snapshot_net)

        result = snap1.copy()
        # compute net rates
        sent_rate = (snap2.bytes_sent - snap1["net_io"].bytes_sent) / 1.0
        recv_rate = (snap2.bytes_recv - snap1["net_io"].bytes_recv) / 1.0
        result["net_sent_per_s"] = sent_rate
        result["net_recv_per_s"] = recv_rate
        result["net_total_sent"] = snap2.bytes_sent
        result["net_total_recv"] = snap2.bytes_recv
        return result

    @commands.command(name="sys", aliases=["piusage", "sysstats", "sysinfo"])
    async def sys(self, ctx: commands.Context):
        """Show host resource usage: CPU, memory, disk, network, uptime and top processes.

        Uses psutil. If psutil is missing the command will ask you to install it.
        """
        if psutil is None:
            await ctx.send(
                "psutil is not installed on the host. Please install it with `python -m pip install psutil` or add it to requirements.txt and run `!update`/restart.`"
            )
            return

        try:
            stats = await self._gather_stats()
        except Exception as exc:
            await ctx.send(f"Failed to gather stats: {exc}")
            return

        boot = datetime.datetime.fromtimestamp(stats["boot_time"]) if stats.get("boot_time") else None
        uptime = datetime.datetime.now() - boot if boot else None

        # Build output lines with aligned columns
        lines = []
        lines.append(f"Uptime: {str(uptime).split('.')[0] if uptime else 'unknown'}")
        lines.append(f"CPU: {stats['cpu_percent']:.1f}%")
        percpu = ", ".join(f"{p:.0f}%" for p in stats.get("cpu_percpu", []))
        if percpu:
            lines.append(f"Per-CPU: {percpu}")
        if stats.get("load_avg"):
            lines.append(f"Load avg: {stats['load_avg'][0]:.2f} {stats['load_avg'][1]:.2f} {stats['load_avg'][2]:.2f}")
        lines.append(
            f"Memory: {_bytes_to_human(stats['mem_used'])} / {_bytes_to_human(stats['mem_total'])} ({stats['mem_percent']:.0f}%)"
        )
        if stats.get("swap_total"):
            lines.append(
                f"Swap: {_bytes_to_human(stats['swap_used'])} / {_bytes_to_human(stats['swap_total'])}"
            )
        lines.append(
            f"Disk (/): {_bytes_to_human(stats['disk_used'])} / {_bytes_to_human(stats['disk_total'])}"
        )
        lines.append(
            f"Net: {_bytes_to_human(int(stats['net_total_recv']))} recv, {_bytes_to_human(int(stats['net_total_sent']))} sent — {_bytes_to_human(int(stats['net_recv_per_s']))}/s ↓  {_bytes_to_human(int(stats['net_sent_per_s']))}/s ↑"
        )

        lines.append("")
        lines.append("Top processes by memory:")
        header = f"{'PID':>6} {'MEM%':>6} {'RSS':>8}  NAME"
        lines.append(header)
        for p in stats.get("top_procs", []):
            pid = p.get("pid")
            memperc = p.get("memory_percent") or 0.0
            rss = getattr(p.get("memory_info"), "rss", 0) if p.get("memory_info") else 0
            name = p.get("name") or "?"
            lines.append(f"{pid:6d} {memperc:6.1f} { _bytes_to_human(rss):>8}  {name}")

        out = "\n".join(lines)
        # send in a code block for monospaced alignment
        await ctx.send(f"```\n{out}\n```")


async def setup(bot: commands.Bot):
    cog = SystemStats(bot)
    await bot.add_cog(cog)
