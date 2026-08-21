import os
import json
import time as _time
import fnmatch as _fnmatch

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(filename, data):
    ensure_data_dir()
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===========================================================================
# Guild-scoped storage
# ===========================================================================
#
# The bot is invitable, so every watchlist belongs to exactly one guild. Files
# that hold per-guild state are shaped like:
#
#     {"_schema": 2, "guilds": {"<guild_id>": <whatever that file stores>}}
#
# Files written before the bot became multi-guild are flat -- the payload sits
# at the top level with no guild dimension. Those are invisible to
# guild-scoped reads until migrate_flat_files_to_guild() adopts them, which
# happens once at startup as soon as we can resolve the legacy CHANNEL_ID to
# a guild. See utils/guild_config.bootstrap_from_legacy_channel.

GUILD_SCHEMA = 2

# Every file that carries per-guild state.
GUILD_SCOPED_FILES = (
    'CID_monitor.json',
    'callsign_monitor.json',
    'callsign_mute.json',
    'type_monitor.json',
    'fake_names.json',
    'a1_monitor.json',
    'a9_monitor.json',
    'atis_monitor.json',
    'workload_monitor.json',
    'workload_stats.json',
    'a4_monitor.json',
)


def _is_migrated(doc):
    return (
        isinstance(doc, dict)
        and doc.get('_schema') == GUILD_SCHEMA
        and isinstance(doc.get('guilds'), dict)
    )


def load_guild_json(filename, guild_id, default=None):
    """Read one guild's slice of a guild-scoped file.

    Returns `default` (or an empty dict) when the guild has nothing stored,
    and also when the file is still flat/unmigrated -- in that state no guild
    owns the data yet, so serving it to an arbitrary guild would leak one
    server's watchlist into another.
    """
    if default is None:
        default = {}
    doc = load_json(filename)
    if not _is_migrated(doc):
        return default
    value = doc['guilds'].get(str(guild_id))
    return default if value is None else value


def save_guild_json(filename, guild_id, value):
    """Write one guild's slice, preserving every other guild's."""
    doc = load_json(filename)
    if not _is_migrated(doc):
        doc = {'_schema': GUILD_SCHEMA, 'guilds': {}}
    doc['guilds'][str(guild_id)] = value
    save_json(filename, doc)


def migrate_flat_files_to_guild(guild_id):
    """Adopt any pre-multi-guild flat files into `guild_id`.

    Idempotent: a file already carrying the guild schema is left alone. Any
    file that is still flat and non-empty gets its whole payload moved under
    the given guild. Returns the list of filenames migrated.
    """
    migrated = []
    for filename in GUILD_SCOPED_FILES:
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            continue
        doc = load_json(filename)
        if _is_migrated(doc) or not doc:
            continue
        save_json(filename, {
            '_schema': GUILD_SCHEMA,
            'guilds': {str(guild_id): doc},
        })
        migrated.append(filename)
    if migrated:
        print(f"[data_manager] migrated {len(migrated)} file(s) to guild "
              f"{guild_id}: {', '.join(migrated)}")
    return migrated


def purge_guild(guild_id):
    """Delete every trace of a guild -- used when the bot is removed."""
    gid = str(guild_id)
    purged = []
    for filename in GUILD_SCOPED_FILES:
        doc = load_json(filename)
        if not _is_migrated(doc):
            continue
        if doc['guilds'].pop(gid, None) is not None:
            save_json(filename, doc)
            purged.append(filename)
    return purged


def save_all():
    save_banned_words(load_banned_words())
    save_banned_word_triggers(load_banned_word_triggers())


def load_all():
    state = {}
    state['banned_words'] = load_banned_words()
    state['banned_word_triggers'] = load_banned_word_triggers()
    return state


# === CID Monitor ===
def load_cid_monitor(guild_id):
    raw = load_guild_json('CID_monitor.json', guild_id, {})
    if isinstance(raw, dict):
        return {int(k): v for k, v in raw.items()}
    return {}


def save_cid_monitor(guild_id, cid_to_monitor):
    save_guild_json('CID_monitor.json', guild_id, cid_to_monitor)


def add_cid_monitor(guild_id, cid, name):
    cid_to_monitor = load_cid_monitor(guild_id)
    cid_to_monitor[int(cid)] = name
    save_cid_monitor(guild_id, cid_to_monitor)


def remove_cid_monitor(guild_id, cid):
    cid_to_monitor = load_cid_monitor(guild_id)
    cid_to_monitor.pop(int(cid), None)
    save_cid_monitor(guild_id, cid_to_monitor)


# === Aircraft Type Monitor ===
def load_type_monitor(guild_id):
    raw = load_guild_json('type_monitor.json', guild_id, {})
    return raw if isinstance(raw, dict) else {}


def save_type_monitor(guild_id, rule_map):
    save_guild_json('type_monitor.json', guild_id, rule_map)


def add_type_monitor(guild_id, pattern, name):
    rule_map = load_type_monitor(guild_id)
    rule_map[pattern] = name
    save_type_monitor(guild_id, rule_map)


def remove_type_monitor(guild_id, pattern):
    rule_map = load_type_monitor(guild_id)
    if pattern in rule_map:
        rule_map.pop(pattern)
        save_type_monitor(guild_id, rule_map)


# === Callsign Monitor ===
def load_callsign_monitor(guild_id):
    raw = load_guild_json('callsign_monitor.json', guild_id, {})
    return raw if isinstance(raw, dict) else {}


def save_callsign_monitor(guild_id, callsign_to_monitor):
    save_guild_json('callsign_monitor.json', guild_id, callsign_to_monitor)


def add_callsign_monitor(guild_id, pattern, name=None):
    callsign_to_monitor = load_callsign_monitor(guild_id)
    if not name:
        name = pattern
    callsign_to_monitor[pattern] = name
    save_callsign_monitor(guild_id, callsign_to_monitor)


def remove_callsign_monitor(guild_id, pattern):
    callsign_to_monitor = load_callsign_monitor(guild_id)
    callsign_to_monitor.pop(pattern, None)
    save_callsign_monitor(guild_id, callsign_to_monitor)


# === Callsign Mute ===
def _prune_expired_callsign_mutes(mutes):
    now = int(_time.time())
    changed = False
    for pat in list(mutes.keys()):
        exp = mutes[pat]
        if exp is not None and exp <= now:
            mutes.pop(pat, None)
            changed = True
    return changed


def load_callsign_mutes(guild_id):
    """Returns dict of {pattern_upper: expires_at_epoch_or_None}.
    Prunes expired entries on read and persists if any pruned."""
    raw = load_guild_json('callsign_mute.json', guild_id, {}) or {}
    mutes = {}
    for k, v in raw.items():
        mutes[k.upper()] = v if (isinstance(v, int) or v is None) else None
    if _prune_expired_callsign_mutes(mutes):
        save_guild_json('callsign_mute.json', guild_id, mutes)
    return mutes


def save_callsign_mutes(guild_id, mutes):
    save_guild_json('callsign_mute.json', guild_id, mutes)


def add_callsign_mute(guild_id, pattern, hours=24):
    """Add or update a mute. hours<=0 means permanent. Returns (pattern_upper, expires_at)."""
    pattern = pattern.upper()
    mutes = load_callsign_mutes(guild_id)
    if hours is None or hours <= 0:
        expires_at = None
    else:
        expires_at = int(_time.time()) + int(hours * 3600)
    mutes[pattern] = expires_at
    save_callsign_mutes(guild_id, mutes)
    return pattern, expires_at


def remove_callsign_mute(guild_id, pattern):
    pattern = pattern.upper()
    mutes = load_callsign_mutes(guild_id)
    existed = pattern in mutes
    if existed:
        mutes.pop(pattern, None)
        save_callsign_mutes(guild_id, mutes)
    return existed


def is_callsign_muted(guild_id, callsign):
    """True if callsign matches any active (non-expired) mute pattern for this
    guild. Supports * wildcards."""
    if not callsign:
        return False
    callsign = callsign.upper()
    mutes = load_callsign_mutes(guild_id)
    for pat in mutes:
        if _fnmatch.fnmatchcase(callsign, pat):
            return True
    return False


# === Banned Words ===
# Global, not guild-scoped: nothing in this repo acts on them (the message
# filter that consumed these lives in a private extension). Kept so the
# load/save cycle in core.py stays intact.
def load_banned_words():
    return load_json('banned_words.json')


def save_banned_words(banned_words):
    save_json('banned_words.json', banned_words)


def update_banned_words(word, replacement):
    banned_words = load_banned_words()
    banned_words[word] = replacement
    save_banned_words(banned_words)


# === Banned Word Triggers ===
def load_banned_word_triggers():
    return load_json('banned_word_triggers.json')


def save_banned_word_triggers(triggers):
    save_json('banned_word_triggers.json', triggers)


def update_banned_word_triggers(trigger, value):
    triggers = load_banned_word_triggers()
    triggers[trigger] = value
    save_banned_word_triggers(triggers)


# === Fake Names (CoC Monitor) ===
def load_fake_names(guild_id):
    data = load_guild_json('fake_names.json', guild_id, [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get('fake_names', [])
    return []


def save_fake_names(guild_id, fake_names):
    save_guild_json('fake_names.json', guild_id, fake_names)


def add_fake_name(guild_id, pattern):
    fake_names = load_fake_names(guild_id)
    if pattern not in fake_names:
        fake_names.append(pattern)
        save_fake_names(guild_id, fake_names)
        return True
    return False


def remove_fake_name(guild_id, pattern):
    fake_names = load_fake_names(guild_id)
    if pattern in fake_names:
        fake_names.remove(pattern)
        save_fake_names(guild_id, fake_names)
        return True
    return False


# === A1 Monitor ===
def load_a1_monitor(guild_id):
    data = load_guild_json('a1_monitor.json', guild_id, [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get('keywords', [])
    return []


def save_a1_monitor(guild_id, keywords):
    save_guild_json('a1_monitor.json', guild_id, keywords)


# === A9 Monitor ===
def load_a9_monitor(guild_id):
    data = load_guild_json('a9_monitor.json', guild_id, [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get('keywords', [])
    return []


def save_a9_monitor(guild_id, keywords):
    save_guild_json('a9_monitor.json', guild_id, keywords)


# === A4 Monitor mute state (CoC) ===
def load_a4_muted(guild_id):
    data = load_guild_json('a4_monitor.json', guild_id, {})
    return data.get('muted', True) if isinstance(data, dict) else True


def save_a4_muted(guild_id, muted):
    data = load_guild_json('a4_monitor.json', guild_id, {})
    if not isinstance(data, dict):
        data = {}
    data['muted'] = bool(muted)
    save_guild_json('a4_monitor.json', guild_id, data)


# === ATIS Monitor ===
def load_atis_monitor(guild_id):
    """Load ATIS monitor data: {airport: {last_codes: {}, last_updated: {}}}"""
    data = load_guild_json('atis_monitor.json', guild_id, {})
    return data if isinstance(data, dict) else {}


def save_atis_monitor(guild_id, atis_data):
    save_guild_json('atis_monitor.json', guild_id, atis_data)


def add_atis_monitor(guild_id, airport):
    atis_data = load_atis_monitor(guild_id)
    airport = airport.upper()
    if airport not in atis_data:
        atis_data[airport] = {
            'last_codes': {},   # {type: code}
            'last_updated': {}  # {type: timestamp}
        }
        save_atis_monitor(guild_id, atis_data)
        return True
    return False


def remove_atis_monitor(guild_id, airport):
    atis_data = load_atis_monitor(guild_id)
    airport = airport.upper()
    if airport in atis_data:
        atis_data.pop(airport)
        save_atis_monitor(guild_id, atis_data)
        return True
    return False


def update_atis_state(guild_id, airport, atis_type, code, updated_at):
    atis_data = load_atis_monitor(guild_id)
    airport = airport.upper()
    if airport in atis_data:
        atis_data[airport]['last_codes'][atis_type] = code
        atis_data[airport]['last_updated'][atis_type] = updated_at
        save_atis_monitor(guild_id, atis_data)


# === Workload Monitor ===
def load_workload_monitor(guild_id):
    data = load_guild_json('workload_monitor.json', guild_id, {})
    if not isinstance(data, dict):
        data = {}
    return {
        'enabled': data.get('enabled', False),
        'threshold': data.get('threshold', 15),
    }


def save_workload_monitor(guild_id, enabled, threshold):
    save_guild_json('workload_monitor.json', guild_id, {
        'enabled': enabled,
        'threshold': threshold,
    })


# === Workload Trigger Stats ===
def load_workload_stats(guild_id):
    """Returns dict keyed by 'CALLSIGN|CID' -> stats record."""
    raw = load_guild_json('workload_stats.json', guild_id, {}) or {}
    return raw if isinstance(raw, dict) else {}


def save_workload_stats(guild_id, stats):
    save_guild_json('workload_stats.json', guild_id, stats)


def record_workload_trigger(guild_id, callsign, cid, name, rating, pilot_count):
    """Increment trigger count for a (callsign, cid) pair. Updates peak and
    last-seen metadata. Safe to call with missing fields."""
    if not callsign:
        return
    callsign = str(callsign).upper()
    cid_str = str(cid) if cid is not None else "N/A"
    key = f"{callsign}|{cid_str}"
    now = int(_time.time())

    stats = load_workload_stats(guild_id)
    rec = stats.get(key) or {
        "callsign": callsign,
        "cid": cid_str,
        "triggers": 0,
        "first_trigger": now,
        "peak_count": 0,
    }
    rec["callsign"] = callsign
    rec["cid"] = cid_str
    if name:
        rec["name"] = name
    if rating:
        rec["rating"] = rating
    rec["triggers"] = int(rec.get("triggers", 0)) + 1
    rec["last_trigger"] = now
    try:
        pc = int(pilot_count)
        rec["last_count"] = pc
        if pc > int(rec.get("peak_count", 0)):
            rec["peak_count"] = pc
    except (TypeError, ValueError):
        pass
    stats[key] = rec
    save_workload_stats(guild_id, stats)


def clear_workload_stats(guild_id):
    save_workload_stats(guild_id, {})
