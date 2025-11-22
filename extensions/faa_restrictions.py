import aiohttp
import textwrap
import re
from bs4 import BeautifulSoup
import discord
from discord.ext import commands, tasks


class FAARestrictions(commands.Cog):
    """FAA restrictions fetch and per-minute monitor.

    Commands:
      - `!faares [REQUESTING] [PROVIDING]` : one-shot fetch
      - `!faaresmon [REQUESTING] [PROVIDING]` : start monitor (or `!faaresmon STOP` to stop)
    """

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

        # monitor state
        self._faa_monitor_filters = ("ALL", "ALL")
        self._faa_monitor_seen = set()
        self._faa_monitor_channel = None

    async def cog_unload(self):
        try:
            if getattr(self, "_faa_monitor_loop", None) and self._faa_monitor_loop.is_running():
                self._faa_monitor_loop.cancel()
        except Exception:
            pass
        try:
            await self.session.close()
        except Exception:
            pass

    async def _get_parsed_rows(self, req: str, prov: str):
        """Fetch FAA restrictions page and return list of (key, daytime, compact)."""
        query_url = f"https://www.fly.faa.gov/restrictions/restrictions?reqFac={req}&provFac={prov}"

        async with self.session.get(query_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"unexpected status {resp.status}")
            text = await resp.text()

        soup = BeautifulSoup(text, "html.parser")

        # Find the table that contains the restriction headers
        target_table = None
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]
            if set(["REQUESTING", "PROVIDING", "RESTRICTION", "START TIME", "STOP TIME"]).issubset(set(headers)):
                target_table = table
                break

        rows = []
        if target_table:
            for tr in target_table.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) >= 5:
                    r = [td.get_text(" ", strip=True) for td in tds[:5]]
                    rows.append(r)
        else:
            # Fallback: look for tr with 5 tds anywhere
            for tr in soup.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) >= 5:
                    r = [td.get_text(" ", strip=True) for td in tds[:5]]
                    rows.append(r)

        parsed_rows = []
        for r_row in rows:
            try:
                r_req, r_prov, r_restr, r_start, r_stop = r_row[:5]
            except Exception:
                continue
            if req != "ALL" and r_req.upper() != req:
                continue
            if prov != "ALL" and r_prov.upper() != prov:
                continue

            # parse start/stop time to extract day and HHMM
            start_hm = ""
            stop_hm = ""
            daynum = ""
            try:
                from datetime import datetime as _dt

                sdt = _dt.strptime(r_start, "%m/%d/%Y %H%M")
                edt = _dt.strptime(r_stop, "%m/%d/%Y %H%M")
                start_hm = sdt.strftime("%H%M")
                stop_hm = edt.strftime("%H%M")
                daynum = str(sdt.day)
            except Exception:
                parts = r_start.split()
                if len(parts) >= 2:
                    daynum = parts[0].split("/")[-1]
                    start_hm = parts[1]
                else:
                    daynum = "?"
                    start_hm = r_start

            daytime = f"{daynum}/{start_hm}"

            compact = r_restr or ""
            has_time = bool(re.search(r"\b\d{3,4}-\d{3,4}\b", compact))

            prov_tokens = re.split(r"[,/\s]+", (r_prov or ""))
            has_provider = False
            for tok in prov_tokens:
                if not tok:
                    continue
                pattern_word = rf"\b{re.escape(tok)}\b"
                pattern_colon = rf"{re.escape(tok)}:"
                if re.search(pattern_word, compact) or re.search(pattern_colon, compact):
                    has_provider = True
                    break

            parts = [compact]
            if start_hm and stop_hm and not has_time:
                parts.append(f"{start_hm}-{stop_hm}")
            if r_prov and not has_provider:
                parts.append(r_prov)

            compact = " ".join(p for p in parts if p).strip()

            key = f"{r_req}|{r_prov}|{r_restr}|{r_start}|{r_stop}"
            parsed_rows.append((key, daytime, compact))

        return parsed_rows

    @commands.command(name="faares")
    async def faares(self, ctx, *args):
        """Fetch FAA restrictions (compact output)."""
        req = "ALL"
        prov = "ALL"
        if len(args) == 1:
            req = args[0].upper()
        elif len(args) >= 2:
            req = args[0].upper()
            prov = args[1].upper()

        try:
            parsed = await self._get_parsed_rows(req, prov)
        except Exception as e:
            await ctx.send(f"FAA restrictions: error fetching page: {e}")
            return

        if not parsed:
            await ctx.send(f"No FAA restrictions found for Requesting={req} Providing={prov}.")
            return

        daytime_list = [day for _k, day, _c in parsed]
        date_w = max((len(d) for d in daytime_list), default=7)
        date_w = max(date_w, len("DATE/TIME"))
        total_target = 160
        rest_w = max(40, total_target - (date_w + 4))

        lines = []
        cont_prefix = " " * (date_w + 4)
        for _k, daytime, compact in parsed:
            wrapped = textwrap.wrap(compact, rest_w) or ["N/A"]
            left = f"{daytime:<{date_w}}"
            first = f"{left}{' ' * 4}{wrapped[0].strip()}"
            lines.append(first)
            for cont in wrapped[1:]:
                lines.append(f"{cont_prefix}{cont.strip()}")

        def _chunks_from_lines(all_lines, limit=1990):
            chunk = []
            size = 0
            for ln in all_lines:
                ln_len = len(ln) + 1
                if size + ln_len > limit and chunk:
                    yield "\n".join(chunk)
                    chunk = [ln]
                    size = ln_len
                else:
                    chunk.append(ln)
                    size += ln_len
            if chunk:
                yield "\n".join(chunk)

        for part in _chunks_from_lines(lines, limit=1900):
            await ctx.send(f"```{part}```")

    @tasks.loop(seconds=60)
    async def _faa_monitor_loop(self):
        req, prov = self._faa_monitor_filters
        try:
            parsed = await self._get_parsed_rows(req, prov)
        except Exception as e:
            print(f"FAA monitor fetch error: {e}")
            return

        channel = self.bot.get_channel(self._faa_monitor_channel) if self._faa_monitor_channel else None

        new_lines = []
        for key, daytime, compact in parsed:
            if key in self._faa_monitor_seen:
                continue
            self._faa_monitor_seen.add(key)
            left = f"{daytime:<{max(len(daytime),7)}}"
            new_lines.append(f"{left}{' ' * 4}{compact}")

        if not new_lines:
            return

        def _chunks_from_lines(all_lines, limit=1990):
            chunk = []
            size = 0
            for ln in all_lines:
                ln_len = len(ln) + 1
                if size + ln_len > limit and chunk:
                    yield "\n".join(chunk)
                    chunk = [ln]
                    size = ln_len
                else:
                    chunk.append(ln)
                    size += ln_len
            if chunk:
                yield "\n".join(chunk)

        if channel:
            for part in _chunks_from_lines(new_lines, limit=1900):
                try:
                    await channel.send(f"```{part}```")
                except Exception as e:
                    print(f"FAA monitor send error: {e}")

    @commands.command(name="faaresmon")
    async def faaresmon(self, ctx, *args):
        """Start/stop a per-minute FAA restrictions monitor.

        Usage:
          `!faaresmon` -> start monitor ALL/ALL
          `!faaresmon ZDC PCT` -> start monitor requesting ZDC, providing PCT
          `!faaresmon STOP` -> stop monitor
        """
        # stop case
        if len(args) == 1 and args[0].upper() in ("STOP", "OFF", "END", "CANCEL"):
            if getattr(self, "_faa_monitor_loop", None) and self._faa_monitor_loop.is_running():
                self._faa_monitor_loop.cancel()
                self._faa_monitor_seen.clear()
                self._faa_monitor_filters = ("ALL", "ALL")
                self._faa_monitor_channel = None
                await ctx.send("FAA restrictions monitor stopped.")
            else:
                await ctx.send("No FAA restrictions monitor is running.")
            return

        req = "ALL"
        prov = "ALL"
        if len(args) == 1:
            req = args[0].upper()
        elif len(args) >= 2:
            req = args[0].upper()
            prov = args[1].upper()

        if getattr(self, "_faa_monitor_loop", None) and self._faa_monitor_loop.is_running():
            await ctx.send("A FAA restrictions monitor is already running. Stop it first with `!faaresmon STOP`.")
            return

        try:
            parsed = await self._get_parsed_rows(req, prov)
        except Exception as e:
            await ctx.send(f"Failed to start monitor: {e}")
            return

        self._faa_monitor_seen = {key for key, _, _ in parsed}
        self._faa_monitor_filters = (req, prov)
        self._faa_monitor_channel = ctx.channel.id
        self._faa_monitor_loop.start()
        await ctx.send(f"FAA restrictions monitor started for Requesting={req} Providing={prov}. Checking every minute.")


async def setup(bot):
    await bot.add_cog(FAARestrictions(bot))

