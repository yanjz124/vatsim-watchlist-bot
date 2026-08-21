import os
import json

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def save_all():
    save_banned_words(load_banned_words())
    save_banned_word_triggers(load_banned_word_triggers())
    save_cid_monitor(load_cid_monitor())
    save_callsign_monitor(load_callsign_monitor())  # if you're using this

def load_all():
    state = {}
    state['banned_words'] = load_banned_words()
    state['banned_word_triggers'] = load_banned_word_triggers()
    state['cid_to_monitor'] = load_cid_monitor()
    state['callsign_to_monitor'] = load_callsign_monitor()  # optional
    return state

def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(filename, data):
    ensure_data_dir()
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


# === CID Monitor ===
def load_cid_monitor():
    raw = load_json('CID_monitor.json')
    if isinstance(raw, dict):
        return {int(k): v for k, v in raw.items()}
    return {}


def save_cid_monitor(cid_to_monitor):
    save_json('CID_monitor.json', cid_to_monitor)

def add_cid_monitor(cid, name):
    cid_to_monitor = load_cid_monitor()
    cid_to_monitor[int(cid)] = name
    save_cid_monitor(cid_to_monitor)

def remove_cid_monitor(cid):
    cid_to_monitor = load_cid_monitor()
    cid_to_monitor.pop(int(cid), None)
    save_cid_monitor(cid_to_monitor)

import os
import json

# ...existing code...

# Aircraft type monitor functions
TYPE_MONITOR_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'type_monitor.json')

def load_type_monitor():
    if not os.path.exists(TYPE_MONITOR_PATH):
        return {}
    with open(TYPE_MONITOR_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_type_monitor(rule_map):
    with open(TYPE_MONITOR_PATH, 'w', encoding='utf-8') as f:
        json.dump(rule_map, f, ensure_ascii=False, indent=2)

def add_type_monitor(pattern, name):
    rule_map = load_type_monitor()
    rule_map[pattern] = name
    save_type_monitor(rule_map)

def remove_type_monitor(pattern):
    rule_map = load_type_monitor()
    if pattern in rule_map:
        rule_map.pop(pattern)
        save_type_monitor(rule_map)

# === Callsign Monitor ===
def load_callsign_monitor():
    return load_json('callsign_monitor.json')

def save_callsign_monitor(callsign_to_monitor):
    save_json('callsign_monitor.json', callsign_to_monitor)

def add_callsign_monitor(pattern, name=None):
    callsign_to_monitor = load_callsign_monitor()
    if not name:
        name = pattern
    callsign_to_monitor[pattern] = name
    save_callsign_monitor(callsign_to_monitor)

def remove_callsign_monitor(pattern):
    callsign_to_monitor = load_callsign_monitor()
    callsign_to_monitor.pop(pattern, None)
    save_callsign_monitor(callsign_to_monitor)


# === Callsign Mute ===
import time as _time
import fnmatch as _fnmatch


def _prune_expired_callsign_mutes(mutes):
    now = int(_time.time())
    changed = False
    for pat in list(mutes.keys()):
        exp = mutes[pat]
        if exp is not None and exp <= now:
            mutes.pop(pat, None)
            changed = True
    return changed


def load_callsign_mutes():
    """Returns dict of {pattern_upper: expires_at_epoch_or_None}.
    Prunes expired entries on read and persists if any pruned."""
    raw = load_json('callsign_mute.json') or {}
    mutes = {}
    for k, v in raw.items():
        mutes[k.upper()] = v if (isinstance(v, int) or v is None) else None
    if _prune_expired_callsign_mutes(mutes):
        save_json('callsign_mute.json', mutes)
    return mutes


def save_callsign_mutes(mutes):
    save_json('callsign_mute.json', mutes)


def add_callsign_mute(pattern, hours=24):
    """Add or update a mute. hours<=0 means permanent. Returns (pattern_upper, expires_at)."""
    pattern = pattern.upper()
    mutes = load_callsign_mutes()
    if hours is None or hours <= 0:
        expires_at = None
    else:
        expires_at = int(_time.time()) + int(hours * 3600)
    mutes[pattern] = expires_at
    save_callsign_mutes(mutes)
    return pattern, expires_at


def remove_callsign_mute(pattern):
    pattern = pattern.upper()
    mutes = load_callsign_mutes()
    existed = pattern in mutes
    if existed:
        mutes.pop(pattern, None)
        save_callsign_mutes(mutes)
    return existed


def is_callsign_muted(callsign):
    """True if callsign matches any active (non-expired) mute pattern. Supports * wildcards."""
    if not callsign:
        return False
    callsign = callsign.upper()
    mutes = load_callsign_mutes()
    for pat in mutes:
        if _fnmatch.fnmatchcase(callsign, pat):
            return True
    return False



# === Banned Words ===
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
def load_fake_names():
    data = load_json('fake_names.json')
    if isinstance(data, list):
        return data
    return data.get('fake_names', [])

def save_fake_names(fake_names):
    save_json('fake_names.json', fake_names)

def add_fake_name(pattern):
    fake_names = load_fake_names()
    if pattern not in fake_names:
        fake_names.append(pattern)
        save_fake_names(fake_names)
        return True
    return False

def remove_fake_name(pattern):
    fake_names = load_fake_names()
    if pattern in fake_names:
        fake_names.remove(pattern)
        save_fake_names(fake_names)
        return True
    return False


# === A1 Monitor ===
def load_a1_monitor():
    data = load_json('a1_monitor.json')
    if isinstance(data, list):
        return data
    return data.get('keywords', [])

def save_a1_monitor(keywords):
    save_json('a1_monitor.json', keywords)


# === A9 Monitor ===
def load_a9_monitor():
    data = load_json('a9_monitor.json')
    if isinstance(data, list):
        return data
    return data.get('keywords', [])

def save_a9_monitor(keywords):
    save_json('a9_monitor.json', keywords)


# === FAA Adv Monitor mute state ===
def load_faa_muted():
    data = load_json('faa_monitor.json')
    return data.get('muted', True)

def save_faa_muted(muted):
    data = load_json('faa_monitor.json')
    data['muted'] = bool(muted)
    save_json('faa_monitor.json', data)


# === A4 Monitor mute state (CoC) ===
def load_a4_muted():
    data = load_json('a4_monitor.json')
    return data.get('muted', True)

def save_a4_muted(muted):
    data = load_json('a4_monitor.json')
    data['muted'] = bool(muted)
    save_json('a4_monitor.json', data)


# === ATIS Monitor ===
def load_atis_monitor():
    """Load the ATIS monitor data. Returns dict of {airport: {last_codes: {}, last_updated: {}}}"""
    return load_json('atis_monitor.json')

def save_atis_monitor(atis_data):
    """Save the ATIS monitor data"""
    save_json('atis_monitor.json', atis_data)

def add_atis_monitor(airport):
    """Add an airport to ATIS monitoring"""
    atis_data = load_atis_monitor()
    airport = airport.upper()
    if airport not in atis_data:
        atis_data[airport] = {
            'last_codes': {},  # {type: code}
            'last_updated': {}  # {type: timestamp}
        }
        save_atis_monitor(atis_data)
        return True
    return False

def remove_atis_monitor(airport):
    """Remove an airport from ATIS monitoring"""
    atis_data = load_atis_monitor()
    airport = airport.upper()
    if airport in atis_data:
        atis_data.pop(airport)
        save_atis_monitor(atis_data)
        return True
    return False

def update_atis_state(airport, atis_type, code, updated_at):
    """Update the last known ATIS state for an airport"""
    atis_data = load_atis_monitor()
    airport = airport.upper()
    if airport in atis_data:
        atis_data[airport]['last_codes'][atis_type] = code
        atis_data[airport]['last_updated'][atis_type] = updated_at
        save_atis_monitor(atis_data)


# === Workload Monitor ===
def load_workload_monitor():
    data = load_json('workload_monitor.json')
    return {
        'enabled': data.get('enabled', False),
        'threshold': data.get('threshold', 15),
    }

def save_workload_monitor(enabled, threshold):
    save_json('workload_monitor.json', {
        'enabled': enabled,
        'threshold': threshold,
    })


# === Workload Trigger Stats ===
def load_workload_stats():
    """Returns dict keyed by 'CALLSIGN|CID' -> stats record."""
    raw = load_json('workload_stats.json') or {}
    return raw if isinstance(raw, dict) else {}


def save_workload_stats(stats):
    save_json('workload_stats.json', stats)


def record_workload_trigger(callsign, cid, name, rating, pilot_count):
    """Increment trigger count for a (callsign, cid) pair. Updates peak and
    last-seen metadata. Safe to call with missing fields."""
    if not callsign:
        return
    callsign = str(callsign).upper()
    cid_str = str(cid) if cid is not None else "N/A"
    key = f"{callsign}|{cid_str}"
    now = int(_time.time())

    stats = load_workload_stats()
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
    save_workload_stats(stats)


def clear_workload_stats():
    save_workload_stats({})
