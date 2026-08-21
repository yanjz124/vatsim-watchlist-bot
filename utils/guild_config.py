# utils/guild_config.py
"""Per-guild configuration: which channel alerts go to, and which of the
global feeds a guild has opted into.

Two different things live behind the word "monitor" in this bot:

  * Watchlists (CIDs, callsigns, aircraft types) are inherently per-guild --
    a guild only hears about the entries it added, so a guild with an empty
    watchlist is silent by construction. No opt-in flag needed.

  * Global feeds (FAA advisories, the new-CID tracker, ATIS, workload, CoC)
    are network-wide and identical for everybody. Those are opt-in per guild
    and default to off, so inviting the bot never spams a server.

Shape of data/guild_config.json:

    {
      "_schema": 1,
      "guilds": {
        "123456789012345678": {
          "alert_channel_id": 987654321098765432,
          "feeds": {"faa": true, "newcid": false, ...}
        }
      }
    }
"""

from .data_manager import load_json, save_json

CONFIG_FILE = 'guild_config.json'
SCHEMA_VERSION = 1

# Feed key -> human description, used by !feeds / /feeds to render the list.
FEEDS = {
    'faa': 'FAA advisories and ground-stop notices',
    'newcid': 'New VATSIM CID registrations',
    'atis': 'Real-world ATIS changes for watched airports',
    'workload': 'Controller workload alerts',
    'coc': 'Code-of-Conduct keyword matches (A1/A4/A9)',
}


def _default_guild():
    return {
        'alert_channel_id': None,
        'feeds': {name: False for name in FEEDS},
    }


def load_guild_config():
    """Return the whole config dict, normalized to the current schema."""
    raw = load_json(CONFIG_FILE) or {}
    guilds = raw.get('guilds')
    if not isinstance(guilds, dict):
        guilds = {}

    normalized = {}
    for gid, entry in guilds.items():
        if not isinstance(entry, dict):
            continue
        base = _default_guild()
        chan = entry.get('alert_channel_id')
        base['alert_channel_id'] = int(chan) if chan else None
        feeds = entry.get('feeds') or {}
        if isinstance(feeds, dict):
            for name in FEEDS:
                base['feeds'][name] = bool(feeds.get(name, False))
        normalized[str(gid)] = base

    return {'_schema': SCHEMA_VERSION, 'guilds': normalized}


def save_guild_config(config):
    save_json(CONFIG_FILE, config)


def get_guild(guild_id):
    """Return this guild's settings. Never persists -- callers that mutate
    should go through the setters below."""
    config = load_guild_config()
    return config['guilds'].get(str(guild_id)) or _default_guild()


def _mutate(guild_id, fn):
    config = load_guild_config()
    gid = str(guild_id)
    entry = config['guilds'].get(gid) or _default_guild()
    fn(entry)
    config['guilds'][gid] = entry
    save_guild_config(config)
    return entry


# === Alert channel ===

def get_alert_channel_id(guild_id):
    return get_guild(guild_id).get('alert_channel_id')


def set_alert_channel(guild_id, channel_id):
    """Bind (or with channel_id=None, unbind) this guild's alert channel."""
    def apply(entry):
        entry['alert_channel_id'] = int(channel_id) if channel_id else None
    return _mutate(guild_id, apply)


def forget_guild(guild_id):
    """Drop all config for a guild -- called when the bot is kicked."""
    config = load_guild_config()
    if config['guilds'].pop(str(guild_id), None) is not None:
        save_guild_config(config)
        return True
    return False


# === Feed subscriptions ===

def is_feed_enabled(guild_id, feed):
    return bool(get_guild(guild_id)['feeds'].get(feed, False))


def set_feed_enabled(guild_id, feed, enabled):
    if feed not in FEEDS:
        raise KeyError(f"unknown feed: {feed}")

    def apply(entry):
        entry['feeds'][feed] = bool(enabled)
    return _mutate(guild_id, apply)


# === Resolution helpers (used by the monitor loops) ===

def configured_guild_ids():
    """Guild IDs that have bound an alert channel."""
    config = load_guild_config()
    return [
        int(gid) for gid, entry in config['guilds'].items()
        if entry.get('alert_channel_id')
    ]


def resolve_alert_channel(bot, guild_id):
    """Return the discord channel object for a guild's alerts, or None if
    it isn't bound, the bot can't see it, or the guild is gone."""
    channel_id = get_alert_channel_id(guild_id)
    if not channel_id:
        return None
    return bot.get_channel(channel_id)


def iter_alert_channels(bot):
    """Yield (guild_id, channel) for every guild with a reachable alert
    channel. Guilds whose channel has been deleted are skipped silently."""
    for guild_id in configured_guild_ids():
        channel = resolve_alert_channel(bot, guild_id)
        if channel is not None:
            yield guild_id, channel


def iter_feed_channels(bot, feed):
    """Yield (guild_id, channel) for guilds subscribed to a global feed."""
    for guild_id, channel in iter_alert_channels(bot):
        if is_feed_enabled(guild_id, feed):
            yield guild_id, channel


def bootstrap_from_legacy_channel(bot, legacy_channel_id):
    """One-time migration for the original single-server deployment.

    Before this bot was invitable, everything posted to one CHANNEL_ID from
    the environment. If that is still set and no guild has been configured
    yet, adopt it: bind the owning guild to that channel and turn every feed
    on, so an existing install behaves exactly as it did before the upgrade.

    Returns the adopted guild id, or None if there was nothing to do.
    """
    if not legacy_channel_id:
        return None
    if configured_guild_ids():
        return None

    channel = bot.get_channel(int(legacy_channel_id))
    if channel is None or getattr(channel, 'guild', None) is None:
        return None

    guild_id = channel.guild.id
    set_alert_channel(guild_id, channel.id)
    for feed in FEEDS:
        set_feed_enabled(guild_id, feed, True)
    print(f"[guild_config] adopted legacy CHANNEL_ID {channel.id} for guild {guild_id}")
    return guild_id
