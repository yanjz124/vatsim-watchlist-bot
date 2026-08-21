# extensions/base_monitor.py

import discord
from discord.ext import commands
from config import atc_rating, pilot_rating
from utils import fetch_vatsim_data, build_status_embed, iter_alert_channels
import io
import time


class VatsimMonitorLoop(commands.Cog):
    """Base class for VATSIM monitor loops that share fingerprinting,
    change detection, embed management, and disconnection handling.

    Multi-guild: the VATSIM datafeed is network-wide, so a cycle fetches it
    exactly once and then fans out over every guild that has bound an alert
    channel, evaluating that guild's own watchlist against the shared
    snapshot. All three caches are keyed by (guild_id, key) so two guilds
    watching the same CID each get their own embed in their own channel.
    """

    # Subclass configuration
    INCLUDE_CONTROLLERS = True
    ENABLE_MAP_REFRESH = True
    ATC_REFRESH_INTERVAL = 600
    PILOT_REFRESH_INTERVAL = 300

    def __init__(self, bot):
        self.bot = bot
        self.status_cache = {}
        self.message_cache = {}
        self.last_map_refresh = {}

    # === Abstract methods (subclass MUST implement) ===

    def load_config(self, guild_id):
        """Return this guild's monitoring config (dict or list)."""
        raise NotImplementedError

    def match_clients(self, guild_id, pilots, controllers):
        """Return {key: [client_data, ...]} matched against this guild's config."""
        raise NotImplementedError

    def get_display_name(self, guild_id, key, client_data):
        """Return display name for a given monitoring key."""
        raise NotImplementedError

    def get_offline_description(self, guild_id, key):
        """Return (title, description) for the offline embed."""
        raise NotImplementedError

    # === Shared methods ===

    def build_fingerprint(self, client_data):
        """Build fingerprint dict from client data.
        Returns (base_fp, rating, is_atc)."""
        source = client_data.get("_source", "unknown")
        is_atc = (source == "controller")
        callsign = client_data.get("callsign", "N/A")
        rating_id = client_data.get("rating") if is_atc else client_data.get("pilot_rating", -1)
        rating = (atc_rating if is_atc else pilot_rating).get(rating_id, f"Unknown ({rating_id})")
        server = client_data.get("server", "N/A")
        start_time = client_data.get("logon_time")

        if is_atc:
            atis_list = client_data.get("text_atis", []) or []
            base_fp = {
                "status": source,
                "callsign": callsign,
                "rating": rating,
                "server": server,
                "start_time": start_time,
                "frequency": client_data.get("frequency"),
                "facility": client_data.get("facility"),
                "visual_range": client_data.get("visual_range"),
                "text_atis": "\n".join(atis_list),
                "last_updated": client_data.get("last_updated"),
                "atis_code": client_data.get("atis_code"),
            }
        else:
            fp = client_data.get("flight_plan") or {}
            aircraft = fp.get("aircraft_short") or fp.get("aircraft_faa") or fp.get("aircraft")
            base_fp = {
                "status": source,
                "callsign": callsign,
                "rating": rating,
                "server": server,
                "start_time": start_time,
                "transponder": client_data.get("transponder"),
                "assigned_transponder": fp.get("assigned_transponder"),
                "aircraft": aircraft,
                "flight_rules": fp.get("flight_rules"),
                "departure": fp.get("departure"),
                "arrival": fp.get("arrival"),
                "alternate": fp.get("alternate"),
                "cruise_tas": fp.get("cruise_tas"),
                "altitude": fp.get("altitude"),
                "deptime": fp.get("deptime"),
                "enroute_time": fp.get("enroute_time"),
                "fuel_time": fp.get("fuel_time"),
                "route": fp.get("route"),
                "remarks": fp.get("remarks"),
            }

        return base_fp, rating, is_atc

    def detect_changes(self, cache_key, base_fp):
        """Compare fingerprint against cache, return (fingerprint_with_meta, old_fp_list)."""
        old_fp_list = self.status_cache.get(cache_key, [])
        old_fp = old_fp_list[0] if old_fp_list else None
        now_epoch = int(time.time())

        if not old_fp:
            changed_keys = ["initial"]
        else:
            changed_keys = sorted([k for k in base_fp if base_fp.get(k) != old_fp.get(k)])

        fingerprint = dict(base_fp)
        fingerprint["updated_keys"] = changed_keys
        fingerprint["updated_at"] = now_epoch
        return fingerprint, old_fp_list

    async def send_or_update_embed(self, channel, cache_key, key, client_data, display_name, rating, is_atc, fingerprint, base_fp, old_fp_list):
        """Send new embed or edit existing one on change, in this guild's channel."""
        if not channel:
            return

        if not old_fp_list:
            embed, file = await build_status_embed(
                client_data=client_data,
                display_name=display_name,
                rating=rating,
                is_atc=is_atc,
                fingerprint=fingerprint
            )
            try:
                if file:
                    sent = await channel.send(embed=embed, file=file)
                else:
                    sent = await channel.send(embed=embed)
                self.message_cache[cache_key] = sent
                if self.ENABLE_MAP_REFRESH:
                    self.last_map_refresh[cache_key] = time.time()
            except Exception as e:
                print(f"Error sending new message for {key}: {e}")

        elif base_fp != old_fp_list[0]:
            embed, file = await build_status_embed(
                client_data=client_data,
                display_name=display_name,
                rating=rating,
                is_atc=is_atc,
                fingerprint=fingerprint
            )
            last_msg = self.message_cache.get(cache_key)
            if last_msg:
                try:
                    if file:
                        await last_msg.edit(embed=embed, attachments=[file])
                    else:
                        await last_msg.edit(embed=embed, attachments=[])
                    if self.ENABLE_MAP_REFRESH:
                        self.last_map_refresh[cache_key] = time.time()
                except Exception as e:
                    print(f"Error editing message for {key}: {e}")

    async def maybe_refresh_map(self, channel, cache_key, key, client_data, display_name, rating, is_atc, base_fp):
        """Periodic map refresh without fingerprint changes."""
        if not self.ENABLE_MAP_REFRESH:
            return

        refresh_interval = self.ATC_REFRESH_INTERVAL if is_atc else self.PILOT_REFRESH_INTERVAL
        last_refresh = self.last_map_refresh.get(cache_key, 0)
        now = time.time()

        if now - last_refresh >= refresh_interval:
            last_msg = self.message_cache.get(cache_key)
            if channel and last_msg:
                try:
                    refresh_fp = dict(self.status_cache.get(cache_key, [base_fp])[0])
                    refresh_fp["updated_keys"] = ["position"]
                    refresh_fp["updated_at"] = int(now)
                    embed, file = await build_status_embed(
                        client_data=client_data,
                        display_name=display_name,
                        rating=rating,
                        is_atc=is_atc,
                        fingerprint=refresh_fp
                    )
                    if file:
                        await last_msg.edit(embed=embed, attachments=[file])
                    else:
                        await last_msg.edit(embed=embed, attachments=[])
                    self.last_map_refresh[cache_key] = now
                except Exception as e:
                    print(f"Error refreshing map for {key}: {e}")

    async def handle_disconnection(self, channel, cache_key, key, guild_id):
        """Edit the embed to grey + 'Disconnected' footer, preserving the map.

        Two gotchas we hit:
          1. Discord's attachment URLs (cdn.discordapp.com / media.discordapp.net)
             are now signed with an expiring `?ex=` / `?hm=` token. Our
             cached Message object holds the URL from minutes/hours ago,
             so attachment.read() against it can 403/404 silently.
             Re-fetching the message gives us fresh URLs.
          2. discord.py's `attachment://filename` resolution only fires
             when a real File is being uploaded in the same request —
             passing existing Attachment objects in attachments= doesn't
             trigger it. So we have to download the existing image bytes
             and re-upload as a fresh File with the same filename.

        Also rebuilds the embed from scratch instead of round-tripping
        through to_dict/from_dict, which carries over the stale image
        URL state we don't want."""
        last_msg = self.message_cache.get(cache_key)
        if last_msg is None:
            return

        try:
            # Refresh URLs (the cached message's attachment URLs may have
            # expired their signed params).
            try:
                last_msg = await last_msg.channel.fetch_message(last_msg.id)
            except Exception as e:
                print(f"[base_monitor] couldn't re-fetch message for {key}: {e}")

            if not last_msg.embeds:
                return

            old = last_msg.embeds[0]
            new = discord.Embed(
                title=old.title,
                description=old.description,
                url=old.url,
                color=discord.Color.from_rgb(0x60, 0x7D, 0x8B),
                timestamp=old.timestamp,
            )
            for field in old.fields:
                new.add_field(name=field.name, value=field.value, inline=field.inline)
            if old.author and old.author.name:
                new.set_author(
                    name=old.author.name,
                    url=old.author.url,
                    icon_url=old.author.icon_url,
                )
            if old.thumbnail and old.thumbnail.url:
                new.set_thumbnail(url=old.thumbnail.url)
            new.set_footer(text="Status: Disconnected")

            file = None
            if last_msg.attachments:
                attachment = last_msg.attachments[0]
                try:
                    data = await attachment.read()
                    file = discord.File(io.BytesIO(data), filename=attachment.filename)
                    new.set_image(url=f"attachment://{attachment.filename}")
                except Exception as e:
                    print(f"[base_monitor] Couldn't re-read attachment for {key}: {e}")

            if file is not None:
                await last_msg.edit(embed=new, attachments=[file])
            else:
                await last_msg.edit(embed=new, attachments=[])
        except Exception as e:
            print(f"Error updating embed footer for disconnected {key}: {e}")

        title, description = self.get_offline_description(guild_id, key)
        embed = discord.Embed(title=title, description=description, color=discord.Color.red())
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending offline message for {key}: {e}")

        self.message_cache.pop(cache_key, None)
        self.last_map_refresh.pop(cache_key, None)

    async def run_monitor_cycle(self):
        """Main loop body. Call from the subclass @tasks.loop method.

        Fetches the network snapshot once, then replays it against every
        configured guild's watchlist.
        """
        targets = list(iter_alert_channels(self.bot))
        if not targets:
            return

        try:
            data = await fetch_vatsim_data()
            if not isinstance(data, dict):
                return
            pilots = data.get("pilots", [])
            controllers = data.get("controllers", []) if self.INCLUDE_CONTROLLERS else []
        except Exception as e:
            print(f"Error fetching VATSIM data: {e}")
            return

        for client in pilots:
            client["_source"] = "pilot"
        for client in controllers:
            client["_source"] = "controller"

        for guild_id, channel in targets:
            try:
                await self._run_guild_cycle(guild_id, channel, pilots, controllers)
            except Exception as e:
                print(f"[{type(self).__name__}] cycle failed for guild {guild_id}: {e}")

    async def _run_guild_cycle(self, guild_id, channel, pilots, controllers):
        """Evaluate one guild's watchlist against an already-fetched snapshot."""
        if not self.load_config(guild_id):
            return

        current_matches = self.match_clients(guild_id, pilots, controllers)

        for key, matched_clients in current_matches.items():
            if not matched_clients:
                continue

            cache_key = (guild_id, key)
            client_data = matched_clients[0]
            display_name = self.get_display_name(guild_id, key, client_data)
            base_fp, rating, is_atc = self.build_fingerprint(client_data)
            fingerprint, old_fp_list = self.detect_changes(cache_key, base_fp)

            await self.send_or_update_embed(
                channel, cache_key, key, client_data, display_name, rating,
                is_atc, fingerprint, base_fp, old_fp_list
            )

            self.status_cache[cache_key] = [base_fp]

            await self.maybe_refresh_map(
                channel, cache_key, key, client_data, display_name, rating,
                is_atc, base_fp
            )

        # Disconnections -- only for this guild's slice of the cache
        for cache_key in list(self.status_cache.keys()):
            cached_guild_id, key = cache_key
            if cached_guild_id != guild_id:
                continue
            if key not in current_matches and self.status_cache.get(cache_key):
                await self.handle_disconnection(channel, cache_key, key, guild_id)
                self.status_cache[cache_key] = []
