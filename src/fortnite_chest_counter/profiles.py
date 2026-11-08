"""
Count profiles (v0.2.2): separate saved counts per person - one profile counts at a time.

A profile is a display name, its own counter file (CERTAIN / APPROX / last chest) and the video source it last counted
from (for example a streamer's Twitch link). Everything else - detector, overlay wording, diagnostic recording, OBS
WebSocket - is shared. The OBS text files always show the ACTIVE profile, so OBS needs no change after a switch.

    state/profiles.json         {"version": 1, "active": "<id>", "profiles": [{"id", "name", "created_at", "source"}]}
    the Default profile         the [state] path of config.toml (state/chest_state.json): an update keeps its counts
    every other profile         state/profiles/<id>.json, next to the Default counter file

No profiles.json (every install before v0.2.2, or nobody ever made a profile) means just the Default profile: exactly
the old behaviour, and reading never creates the file. A damaged profiles.json is moved aside and rebuilt from the
counter files in state/profiles/, so a bad file never loses counts. Deleting a profile moves its counter file to
state/profiles/deleted/ instead of erasing it.
"""

import json
import re
import time
import unicodedata
from pathlib import Path

DEFAULT_ID = "default"
DEFAULT_NAME = "Default"
REGISTRY_NAME = "profiles.json"
MAX_NAME = 40
MAX_PROFILES = 100
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10)),
             "deleted", DEFAULT_ID}
# The video source remembered per profile: the same keys the app writes to config.toml [live] when counting starts.
SOURCE_KEYS = ("source", "device", "monitor", "window", "url", "stream_stability")


class ProfileError(ValueError):
    """A profile request that cannot be done (bad name, unknown profile, ...). The message is meant for the user."""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def registry_path(base_state_path):
    """profiles.json sits next to the Default counter file."""
    return Path(base_state_path).parent / REGISTRY_NAME


def profile_state_path(base_state_path, profile_id):
    if profile_id == DEFAULT_ID:
        return Path(base_state_path)
    return Path(base_state_path).parent / "profiles" / f"{profile_id}.json"


def _default_entry():
    return {"id": DEFAULT_ID, "name": DEFAULT_NAME, "created_at": None, "source": {}}


def _fresh_registry():
    return {"version": 1, "active": DEFAULT_ID, "profiles": [_default_entry()]}


def check_name(name, registry=None, ignore_id=None):
    """-> the cleaned name, or raises ProfileError with a message for the user."""
    if not isinstance(name, str):
        raise ProfileError("The profile name must be text.")
    clean = " ".join(name.split())
    if not clean:
        raise ProfileError("Type a name for the profile.")
    if len(clean) > MAX_NAME:
        raise ProfileError(f"Profile names can be at most {MAX_NAME} characters long.")
    if any(unicodedata.category(c) in ("Cc", "Cs") for c in clean):        # control characters (emoji joiners are fine)
        raise ProfileError("The profile name contains characters that cannot be shown.")
    for p in (registry or {}).get("profiles", []):
        if p["id"] != ignore_id and p["name"].casefold() == clean.casefold():
            raise ProfileError(f'There is already a profile called "{p["name"]}".')
    return clean


def slug(name, taken=()):
    """A file-name-safe, unique id from a display name: "João Ação" -> "joao-acao", "CON" -> "p-con"."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:32].strip("-") or "profile"
    if base in _RESERVED:
        base = f"p-{base}"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _clean_source(source):
    if not isinstance(source, dict):
        return {}
    out = {}
    for key in SOURCE_KEYS:
        value = source.get(key)
        if key == "monitor":
            if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
                out[key] = value
        elif isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _validate(data):
    """-> a clean registry dict, or raises ValueError if the file is not a usable registry."""
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
        raise ValueError("not a profile list")
    seen, names, profiles = set(), set(), []
    for p in data["profiles"]:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not isinstance(p.get("name"), str):
            raise ValueError("a profile has no id or name")
        pid = p["id"]
        if pid != DEFAULT_ID and (slug(pid) != pid or pid in _RESERVED):
            raise ValueError(f"bad profile id {pid!r}")
        name = " ".join(p["name"].split())[:MAX_NAME] or pid
        if pid in seen or name.casefold() in names:
            raise ValueError(f"duplicate profile {pid!r}")
        seen.add(pid)
        names.add(name.casefold())
        profiles.append({"id": pid, "name": name, "created_at": p.get("created_at"),
                         "source": _clean_source(p.get("source"))})
    if DEFAULT_ID not in seen:
        profiles.insert(0, _default_entry())
    active = data.get("active") if data.get("active") in seen else DEFAULT_ID
    return {"version": 1, "active": active, "profiles": profiles}


def _rebuild(base_state_path):
    """Registry from the counter files that exist in state/profiles/ (used when profiles.json is damaged)."""
    reg = _fresh_registry()
    folder = Path(base_state_path).parent / "profiles"
    if folder.is_dir():
        for f in sorted(folder.glob("*.json")):
            pid = f.stem
            if slug(pid) == pid and pid not in _RESERVED and len(reg["profiles"]) < MAX_PROFILES:
                reg["profiles"].append({"id": pid, "name": pid, "created_at": None, "source": {}})
    return reg


def load(base_state_path, warn=None):
    """The registry for the Default counter file `base_state_path` (read-only unless the file is damaged)."""
    path = registry_path(base_state_path)
    if not path.exists():
        return _fresh_registry()
    try:
        return _validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError) as error:
        reg = _rebuild(base_state_path)
        moved = path.with_name(f"{path.stem}.damaged-{time.strftime('%Y%m%d_%H%M%S')}{path.suffix}")
        try:
            path.replace(moved)
            save(base_state_path, reg)
            where = f"it was moved to {moved.name}"
        except OSError:
            where = "it could not be moved aside"
        if warn:
            warn(f"{path} could not be read ({error}); {where} and the profile list was rebuilt from the saved counter "
                 f"files ({len(reg['profiles'])} profiles; names may need renaming). No counts were lost.")
        return reg


def save(base_state_path, registry):
    from fortnite_chest_counter.counter import atomic_write
    atomic_write(registry_path(base_state_path), json.dumps(registry, indent=2, ensure_ascii=False) + "\n")


def get(registry, profile_id):
    for p in registry["profiles"]:
        if p["id"] == profile_id:
            return p
    raise ProfileError(f"There is no profile with the id {profile_id!r}.")


def find(registry, name_or_id):
    """A profile by display name (any case) or id. -> entry, or raises ProfileError listing the profiles."""
    wanted = " ".join(str(name_or_id).split()).casefold()
    for p in registry["profiles"]:
        if p["id"] == name_or_id or p["name"].casefold() == wanted:
            return p
    names = ", ".join(f'"{p["name"]}"' for p in registry["profiles"])
    raise ProfileError(f'There is no profile called "{name_or_id}". Profiles: {names}.')


def active(registry):
    return get(registry, registry["active"])


def create(base_state_path, name, activate=True):
    """New profile with its own counter file at 0. -> its entry."""
    from fortnite_chest_counter.counter import fresh_state, save_state
    reg = load(base_state_path)
    if len(reg["profiles"]) >= MAX_PROFILES:
        raise ProfileError(f"You can have at most {MAX_PROFILES} profiles. Delete one you no longer need first.")
    clean = check_name(name, reg)
    pid = slug(clean, {p["id"] for p in reg["profiles"]})
    state_path = profile_state_path(base_state_path, pid)
    while state_path.exists():                      # a file left behind by hand: never overwrite counts
        pid = slug(clean, {p["id"] for p in reg["profiles"]} | {pid})
        state_path = profile_state_path(base_state_path, pid)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    save_state(state_path, fresh_state())
    entry = {"id": pid, "name": clean, "created_at": _now(), "source": {}}
    reg["profiles"].append(entry)
    if activate:
        reg["active"] = pid
    save(base_state_path, reg)
    return entry


def rename(base_state_path, profile_id, name):
    """Changes only the display name: the id and the counter file stay the same."""
    reg = load(base_state_path)
    entry = get(reg, profile_id)
    entry["name"] = check_name(name, reg, ignore_id=profile_id)
    save(base_state_path, reg)
    return entry


def delete(base_state_path, profile_id):
    """Removes a profile (never the Default one). Its counter file is moved to state/profiles/deleted/, not erased.
    Deleting the active profile makes Default active. -> where the counter file went, or None if it had none."""
    if profile_id == DEFAULT_ID:
        raise ProfileError("The Default profile cannot be deleted (you can reset its counts instead).")
    reg = load(base_state_path)
    get(reg, profile_id)
    source = profile_state_path(base_state_path, profile_id)
    moved = None
    if source.exists():
        folder = source.parent / "deleted"
        folder.mkdir(parents=True, exist_ok=True)
        moved = folder / f"{profile_id}-{time.strftime('%Y%m%d_%H%M%S')}.json"
        source.replace(moved)
    reg["profiles"] = [p for p in reg["profiles"] if p["id"] != profile_id]
    if reg["active"] == profile_id:
        reg["active"] = DEFAULT_ID
    save(base_state_path, reg)
    return moved


def set_active(base_state_path, profile_id):
    reg = load(base_state_path)
    entry = get(reg, profile_id)
    if reg["active"] != profile_id:
        reg["active"] = profile_id
        save(base_state_path, reg)
    return entry


def remember_source(base_state_path, profile_id, source):
    """Store the video source a profile counted from, so switching back to it restores it. Writes only on a change,
    and never creates profiles.json just for the Default profile's source."""
    reg = load(base_state_path)
    entry = get(reg, profile_id)
    clean = _clean_source(source)
    if entry.get("source") == clean or (profile_id == DEFAULT_ID and not registry_path(base_state_path).exists()):
        return
    entry["source"] = clean
    save(base_state_path, reg)


def apply(cfg, choice=None, warn=None):
    """Point cfg's counter file at the active profile (or `choice`: a name or id, for this run only). Adds
    cfg["profile"] = {"id", "name", "state_base"}. Idempotent. -> the profile entry."""
    if "profile" in cfg:
        base = cfg["profile"]["state_base"]
    else:
        base = cfg["state"]["path"]
    reg = load(base, warn=warn)
    entry = find(reg, choice) if choice else active(reg)
    cfg["state"]["path"] = str(profile_state_path(base, entry["id"]))
    cfg["profile"] = {"id": entry["id"], "name": entry["name"], "state_base": str(base)}
    return entry
