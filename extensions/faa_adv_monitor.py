import os
import json
import hashlib
import asyncio
from urllib.parse import urljoin
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup
from typing import Optional
import discord
from discord.ext import commands, tasks

from config import CHANNEL_ID


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT_DIR, "data")
SEEN_FILE = os.path.join(DATA_DIR, "seen_faa.json")
BASE_URL = "https://www.fly.faa.gov"
LIST_URL = "https://www.fly.faa.gov/adv/adv_spt"


def _load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, indent=2)


class FAAAdvMonitor(commands.Cog):
    """Poll the FAA adv_spt page and post new advisories to a Discord channel.

    - Poll interval: 10 minutes
    - Persists seen advisory IDs to `data/seen_faa.json`
    """

    def __init__(self, bot):
        self.bot = bot
        self.seen = _load_seen()
        self.session = aiohttp.ClientSession()
        self.faa_loop.start()

    async def cog_unload(self):
        self.faa_loop.cancel()
        # close session
        try:
            await self.session.close()
        except Exception:
            pass

    @tasks.loop(minutes=10)
    async def faa_loop(self):
        try:
            async with self.session.get(LIST_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    print(f"FAA monitor: unexpected status {resp.status}")
                    return
                text = await resp.text()
        except Exception as e:
            print(f"FAA monitor: error fetching list page: {e}")
            return

        soup = BeautifulSoup(text, "html.parser")

        # Try to find anchors first
        anchors = [a for a in soup.find_all("a", href=True) if "/adv/" in a["href"]]

        if anchors:
            # Process anchors as before
            new_items = []
            for a in anchors:
                href = a["href"].strip()
                title = (a.get_text() or "").strip()
                full_url = urljoin(BASE_URL, href)
                digest = hashlib.sha256(f"{full_url}|{title}".encode("utf-8")).hexdigest()
                if digest in self.seen:
                    continue
                self.seen.add(digest)
                new_items.append({"title": title or full_url, "url": full_url})

            if not new_items:
                return

            _save_seen(self.seen)

            channel = self.bot.get_channel(CHANNEL_ID)
            if not channel:
                print("FAA monitor: target channel not found")
                return

            for item in new_items:
                embed = discord.Embed(
                    title="FAA: New advisory / special publication",
                    description=item["title"],
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Link", value=item["url"], inline=False)
                embed.set_footer(text="Source: fly.faa.gov")

                try:
                    await channel.send(embed=embed)
                except Exception as e:
                    print(f"FAA monitor: failed to send embed: {e}")
        else:
            # Fallback to raw text parsing
            body_text = soup.get_text(separator="\n")
            sections = self._parse_faa_text(body_text)
            full_digest = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
            if full_digest in self.seen:
                return
            self.seen.add(full_digest)
            _save_seen(self.seen)

            channel = self.bot.get_channel(CHANNEL_ID)
            if not channel:
                print("FAA monitor: target channel not found")
                return

            embeds = self._create_embeds_from_sections(sections)
            for embed in embeds:
                try:
                    await channel.send(embed=embed)
                except Exception as e:
                    print(f"FAA monitor: failed to send embed: {e}")

    @commands.command(name="faaadv")
    async def faaadv(self, ctx, mode: Optional[str] = None, limit: int = 5):
        """Fetch FAA advisories and post them as embeds.

        Usage: `!faaadv` — posts up to 5 latest advisories
               `!faaadv new` — posts up to 5 advisories not seen before and marks them seen
               `!faaadv new 10` — post up to 10 new advisories
        """
        # Debug: announce locally that the command was invoked (helps diagnose permissions / handler execution)
        print(f"faaadv invoked by {ctx.author} in #{getattr(ctx.channel, 'name', ctx.channel)} mode={mode} limit={limit}", flush=True)

        print("faaadv: starting fetch", flush=True)

        try:
            async with self.session.get(LIST_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    await ctx.send(f"FAA monitor: unexpected status {resp.status}")
                    return
                text = await resp.text()
        except Exception as e:
            await ctx.send(f"FAA monitor: error fetching list page: {e}")
            return

        soup = BeautifulSoup(text, "html.parser")
        body_text = soup.get_text(separator="\n")
        sections = self._parse_faa_text(body_text)
        full_digest = hashlib.sha256(body_text.encode("utf-8")).hexdigest()

        print(f"faaadv: parsed {len(sections)} sections, digest={full_digest[:16]}...", flush=True)

        new_only = (mode or "").lower() == "new"
        if new_only and full_digest in self.seen:
            print("faaadv: new_only and already seen, sending 'No new FAA advisories.'", flush=True)
            await ctx.send("No new FAA advisories.")
            return

        embeds = self._create_embeds_from_sections(sections)
        print(f"faaadv: created {len(embeds)} embeds", flush=True)
        if not embeds:
            print("faaadv: no embeds, sending 'No FAA advisories found.'", flush=True)
            await ctx.send("No FAA advisories found.")
            return

        for i, embed in enumerate(embeds):
            print(f"faaadv: sending embed {i+1}/{len(embeds)}", flush=True)
            try:
                await ctx.send(embed=embed)
                print(f"faaadv: embed {i+1} sent successfully", flush=True)
            except Exception as e:
                print(f"faaadv: embed {i+1} send failed: {e}, sending error message", flush=True)
                await ctx.send(f"Failed to send embed: {e}")

        if new_only:
            self.seen.add(full_digest)
            _save_seen(self.seen)
            print("faaadv: marked as seen", flush=True)
    
    

    def _parse_faa_text(self, text):
        # Known section headers
        headers = [
            "EVENT TIME:",
            "STAFFING TRIGGER(S):",
            "TERMINAL CONSTRAINTS:",
            "TERMINAL ACTIVE:",
            "TERMINAL PLANNED:",
            "EN ROUTE CONSTRAINTS:",
            "EN ROUTE ACTIVE:",
            "EN ROUTE PLANNED:",
            "CDRS/SWAP/CAPPING/TUNNELING/HOTLINE/DIVERSION RECOVERY:",
            "RUNWAY/EQUIPMENT/POSSIBLE SYSTEM IMPACT REPORTS (SIRs):",
            "AIRSPACE FLOW PROGRAM(S) ACTIVE:",
            "AIRSPACE FLOW PROGRAM(S) PLANNED:",
            "PLANNED LAUNCH/REENTRY:",
            "FLIGHT CHECK(S):",
            "VIP MOVEMENT(S):",
            "NEXT PLANNING WEBINAR:"
        ]
        
        sections = []
        lines = text.splitlines()
        current_header = None
        current_content = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Check if line is a header
            if any(line.startswith(h) for h in headers):
                # Save previous section
                if current_header:
                    content = "\n".join(current_content).strip()
                    if content:
                        sections.append((current_header, content))
                # Start new section
                current_header = line
                current_content = []
            else:
                if current_header:
                    current_content.append(line)
        
        # Last section
        if current_header:
            content = "\n".join(current_content).strip()
            if content:
                sections.append((current_header, content))
        
        return sections

    def _create_embeds_from_sections(self, sections):
        embeds = []
        embed = discord.Embed(
            title="FAA: Current Operations Plan Advisory",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Source: fly.faa.gov/adv/adv_spt")
        
        for header, content in sections:
            # Clean header
            field_name = header.rstrip(":")
            field_value = content[:1020] + ("..." if len(content) > 1020 else "")
            
            # Check if adding this field would exceed embed limits
            # Roughly: title + desc + fields
            # If current embed has too many chars, start new
            current_chars = len(str(embed.title or "")) + len(str(embed.description or "")) + sum(len(str(f.name)) + len(str(f.value)) for f in embed.fields)
            if current_chars + len(field_name) + len(field_value) > 5500 or len(embed.fields) >= 20:
                embeds.append(embed)
                embed = discord.Embed(
                    title="FAA: Current Operations Plan Advisory (continued)",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text="Source: fly.faa.gov/adv/adv_spt")
            
            embed.add_field(name=field_name, value=field_value, inline=False)
        
        if embed.fields:
            embeds.append(embed)
        
        return embeds


async def setup(bot):
    await bot.add_cog(FAAAdvMonitor(bot))
