# extensions/guild_setup.py
"""Onboarding for an invited server: bind an alert channel, choose feeds.

Everything else in this bot is a `!` prefix command, but a server admin who
has just invited the bot has no way to know that. These few setup commands
are exposed as slash commands so they are discoverable from Discord's own
command picker; each one has a `!` twin for consistency with the rest.
"""

import hashlib
import json

import discord
from discord import app_commands
from discord.ext import commands

from config import ADMIN_ID, CHANNEL_ID
from utils.data_manager import load_json, save_json
from utils import (
    FEEDS,
    get_alert_channel_id,
    set_alert_channel,
    is_feed_enabled,
    set_feed_enabled,
    forget_guild,
    bootstrap_from_legacy_channel,
    migrate_flat_files_to_guild,
    purge_guild,
)


SYNC_STATE_FILE = "slash_sync.json"


def _tree_signature(tree):
    """Fingerprint what a sync would publish, so an unchanged tree can skip it.

    Built from the fields Discord actually stores -- names, descriptions and
    each option's name/type/required/choices -- so an edit to any of them
    changes the hash and a pure code change does not.
    """
    def describe(cmd):
        if isinstance(cmd, app_commands.Group):
            return {
                "name": cmd.name,
                "description": cmd.description,
                "subcommands": sorted((describe(c) for c in cmd.commands),
                                      key=lambda d: d["name"]),
            }
        return {
            "name": cmd.name,
            "description": cmd.description,
            "options": [
                {
                    "name": p.name,
                    "type": str(p.type),
                    "required": p.required,
                    "description": p.description,
                    "choices": [str(c.value) for c in (p.choices or [])],
                }
                for p in cmd.parameters
            ],
        }

    payload = sorted((describe(c) for c in tree.get_commands()),
                     key=lambda d: d["name"])
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _config_embed(guild, channel_id):
    channel = guild.get_channel(channel_id) if channel_id else None
    embed = discord.Embed(
        title=f"VATSIM watchlist settings — {guild.name}",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Alert channel",
        value=channel.mention if channel else "*not set* — run `/setchannel`",
        inline=False,
    )

    lines = []
    for feed, description in FEEDS.items():
        mark = "on " if is_feed_enabled(guild.id, feed) else "off"
        lines.append(f"`{mark}` **{feed}** — {description}")
    embed.add_field(name="Global feeds", value="\n".join(lines), inline=False)

    embed.set_footer(
        text="Watchlists (!cidmon, !csmon, !typemon) post whenever they have "
             "entries. Global feeds are opt-in with /feeds."
    )
    return embed


class GuildSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # === lifecycle ===

    @commands.Cog.listener()
    async def on_ready(self):
        """Adopt the pre-multi-guild deployment, then publish slash commands.

        bootstrap_from_legacy_channel is a no-op once any guild is configured,
        so this is safe to run on every reconnect.
        """
        adopted = bootstrap_from_legacy_channel(self.bot, CHANNEL_ID)
        if adopted:
            migrate_flat_files_to_guild(adopted)

        await self.sync_if_changed()

    async def sync_if_changed(self, force=False):
        """Publish slash commands, but only when they actually differ.

        on_ready fires on every reconnect, not just at boot, and a sync is a
        rate-limited write of the whole command set -- so doing it on each one
        spends an API call to tell Discord what it already knows. Compare a
        fingerprint of the tree against the last published one instead, and
        sync only on a real change. !synccommands forces it when Discord's
        copy has drifted from ours.
        """
        signature = _tree_signature(self.bot.tree)
        state = load_json(SYNC_STATE_FILE)
        if not force and state.get("signature") == signature:
            print(f"[guild_setup] slash commands unchanged "
                  f"({state.get('count', '?')} published) -- no sync needed")
            return None

        try:
            synced = await self.bot.tree.sync()
        except Exception as e:
            # Leave the stored signature alone so the next ready retries.
            print(f"[guild_setup] slash command sync failed: {e}")
            return None

        save_json(SYNC_STATE_FILE, {"signature": signature, "count": len(synced)})
        print(f"[guild_setup] synced {len(synced)} slash command(s)")
        return synced

    @commands.command(name="synccommands")
    async def synccommands(self, ctx):
        """Force a slash command sync (admin only)."""
        if ctx.author.id != ADMIN_ID:
            await ctx.send("Unauthorized.")
            return
        synced = await self.sync_if_changed(force=True)
        if synced is None:
            await ctx.send("Sync failed — check the logs.")
        else:
            await ctx.send(f"Published {len(synced)} slash command(s).")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Say hello somewhere the inviter can see, without assuming a channel."""
        target = guild.system_channel
        if target is None or not target.permissions_for(guild.me).send_messages:
            target = next(
                (c for c in guild.text_channels
                 if c.permissions_for(guild.me).send_messages),
                None,
            )
        if target is None:
            return

        embed = discord.Embed(
            title="VATSIM watchlist bot",
            description=(
                "Thanks for the invite. Nothing will post until you point me "
                "at a channel:\n\n"
                "**1.** `/setchannel #your-channel` — where alerts go\n"
                "**2.** `/feeds` — turn on network-wide feeds (all off by default)\n"
                "**3.** `!cidmon add <CID>` / `!csmon add <CALLSIGN>` — build a watchlist\n\n"
                "`/config` shows the current settings, `!help` lists everything."
            ),
            color=discord.Color.blurple(),
        )
        try:
            await target.send(embed=embed)
        except Exception as e:
            print(f"[guild_setup] couldn't greet guild {guild.id}: {e}")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Don't keep watchlists for a server that removed the bot."""
        forget_guild(guild.id)
        purge_guild(guild.id)
        print(f"[guild_setup] purged data for removed guild {guild.id}")

    # === slash commands ===

    @app_commands.command(
        name="setchannel",
        description="Choose the channel this server's VATSIM alerts post to.",
    )
    @app_commands.describe(channel="Channel to post alerts in (defaults to the current one)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setchannel(self, interaction: discord.Interaction,
                         channel: discord.TextChannel = None):
        channel = channel or interaction.channel

        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.response.send_message(
                f"I need **Send Messages** and **Embed Links** in {channel.mention}.",
                ephemeral=True,
            )
            return
        if not perms.attach_files:
            await interaction.response.send_message(
                f"Heads up: I can't **Attach Files** in {channel.mention}, so "
                f"position maps won't render. Setting it anyway.",
                ephemeral=True,
            )
            set_alert_channel(interaction.guild.id, channel.id)
            return

        set_alert_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"Alerts will post in {channel.mention}. Use `/feeds` to subscribe "
            f"to network-wide feeds, or `!cidmon add <CID>` to start a watchlist.",
            ephemeral=True,
        )

    @app_commands.command(
        name="config",
        description="Show this server's alert channel and feed subscriptions.",
    )
    @app_commands.guild_only()
    async def config(self, interaction: discord.Interaction):
        embed = _config_embed(interaction.guild,
                              get_alert_channel_id(interaction.guild.id))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="feeds",
        description="Turn a network-wide feed on or off for this server.",
    )
    @app_commands.describe(feed="Which feed to change", enabled="On or off")
    @app_commands.choices(feed=[
        app_commands.Choice(name=name, value=name) for name in FEEDS
    ])
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def feeds(self, interaction: discord.Interaction,
                    feed: app_commands.Choice[str] = None,
                    enabled: bool = None):
        if feed is None or enabled is None:
            embed = _config_embed(interaction.guild,
                                  get_alert_channel_id(interaction.guild.id))
            embed.description = "Use `/feeds feed:<name> enabled:<true|false>` to change one."
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if enabled and not get_alert_channel_id(interaction.guild.id):
            await interaction.response.send_message(
                "Set an alert channel first with `/setchannel`.", ephemeral=True)
            return

        set_feed_enabled(interaction.guild.id, feed.value, enabled)
        state = "on" if enabled else "off"
        await interaction.response.send_message(
            f"Feed **{feed.value}** is now **{state}** for this server.",
            ephemeral=True,
        )

    # === prefix twins ===

    # Prefix twin of the /setchannel app command above. Deliberately NOT
    # hybrid: that would register a second /setchannel and the tree
    # rejects the duplicate, taking this whole cog down with it.
    @commands.command(name="setchannel")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def setchannel_prefix(self, ctx, channel: discord.TextChannel = None):
        """Set this server's alert channel. Usage: !setchannel [#channel]"""
        channel = channel or ctx.channel
        perms = channel.permissions_for(ctx.guild.me)
        if not (perms.send_messages and perms.embed_links):
            await ctx.send(f"I need **Send Messages** and **Embed Links** in {channel.mention}.")
            return
        set_alert_channel(ctx.guild.id, channel.id)
        await ctx.send(f"Alerts will post in {channel.mention}.")

    # Prefix twin of the /config app command above. Deliberately NOT
    # hybrid: that would register a second /config and the tree
    # rejects the duplicate, taking this whole cog down with it.
    @commands.command(name="config")
    @commands.guild_only()
    async def config_prefix(self, ctx):
        """Show this server's alert channel and feed subscriptions."""
        await ctx.send(embed=_config_embed(ctx.guild, get_alert_channel_id(ctx.guild.id)))

    # Prefix twin of the /feeds app command above. Deliberately NOT
    # hybrid: that would register a second /feeds and the tree
    # rejects the duplicate, taking this whole cog down with it.
    @commands.command(name="feeds")
    @commands.guild_only()
    async def feeds_prefix(self, ctx, feed: str = None, state: str = None):
        """Toggle a global feed. Usage: !feeds [<feed> on|off]"""
        if feed is None or state is None:
            await ctx.send(embed=_config_embed(ctx.guild, get_alert_channel_id(ctx.guild.id)))
            return

        feed = feed.lower()
        if feed not in FEEDS:
            await ctx.send(f"Unknown feed `{feed}`. Options: {', '.join(FEEDS)}")
            return

        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send("You need the **Manage Server** permission to change feeds.")
            return

        enabled = state.lower() in ("on", "true", "enable", "enabled", "yes", "1")
        if enabled and not get_alert_channel_id(ctx.guild.id):
            await ctx.send("Set an alert channel first with `!setchannel`.")
            return

        set_feed_enabled(ctx.guild.id, feed, enabled)
        await ctx.send(f"Feed **{feed}** is now **{'on' if enabled else 'off'}** for this server.")

    @commands.hybrid_command(name="invite")
    async def invite(self, ctx):
        """Get an invite link for this bot."""
        if self.bot.user is None:
            await ctx.send("Not ready yet, try again in a moment.")
            return
        perms = discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
        )
        url = discord.utils.oauth_url(
            self.bot.user.id,
            permissions=perms,
            scopes=("bot", "applications.commands"),
        )
        await ctx.send(f"Invite me to another server:\n<{url}>")


async def setup(bot):
    await bot.add_cog(GuildSetup(bot))
