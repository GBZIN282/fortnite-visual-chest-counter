"""
User settings: a human-editable config.toml, with safe defaults and clear warnings.

Precedence:  built-in defaults  ->  config file  ->  command-line overrides

  * no config file            -> defaults (not an error)
  * a field is missing        -> the default for just that field
  * a value is invalid        -> warning, default for just that field
  * a key/section is unknown  -> warning (it is probably a typo), ignored
  * the file is not valid TOML-> warning, ALL defaults

Only user-facing behaviour is configurable here; fragile detector internals stay constants in
the code. Also home of the single count-formatting helper used by every user-facing number.
"""

import tomllib
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config.toml")

DEFAULTS = {
    "detector": {
        "process_fps": 15,                      # detector cadence; 15 is what the detectors were developed at
        "languages": ["en", "pt"],              # chest-word templates to use
        "certain_min_tier": "HIGH",             # "HIGH": CERTAIN+HIGH popups are certain; "CERTAIN": only CERTAIN
        "count_supported_medium_as_approx": True,       # MEDIUM popup + prompt + chest-like object
        "count_interaction_object_as_approx": True,     # prompt + chest-like object without a popup
        "medium_counts_alone_languages": ["en"],        # languages whose MEDIUM popups count as approx by themselves
    },
    "display": {
        "certain_label": "CERTAIN OPENED CHESTS",
        "approximate_label": "APPROX. OPENED CHESTS",
        "combined_status_format": "{certain} certain • ~{approximate} estimated",
        "use_thousands_separator": True,
    },
    "state": {
        "persist": True,
        "path": "state/chest_state.json",
        "obs_dir": "obs_output",
    },
    "logging": {
        "enabled": True,
        "log_candidates": True,                 # also log events that were NOT counted
        "save_snapshots": False,                # save a small PNG of the popup area for every popup event (for reporting misses)
        "dir": "logs",
    },
    "live": {
        "source": "obs-camera",                 # obs-camera | device | desktop | file
        "device": "OBS Virtual Camera",         # DirectShow device name for --source device
        "monitor": 1,                           # monitor number for --source desktop
        "status_interval_seconds": 5,
    },
}

_TIERS = ("CERTAIN", "HIGH")
_SOURCES = ("obs-camera", "device", "desktop", "file")


def format_count(value, thousands=True):
    """The ONE place counts become text: 0, 999, 1,000, 1,234,567 (or raw integers if disabled)."""
    value = int(value)
    return f"{value:,}" if thousands else str(value)


def _check(section, key, value):
    """Return (ok, problem) for one value."""
    default = DEFAULTS[section][key]
    if isinstance(default, bool):
        return (isinstance(value, bool), "must be true or false")
    if key == "process_fps":
        return (isinstance(value, int) and not isinstance(value, bool) and 5 <= value <= 30, "must be a whole number from 5 to 30")
    if key == "certain_min_tier":
        return (value in _TIERS, f"must be one of {list(_TIERS)}")
    if key == "source":
        return (value in _SOURCES, f"must be one of {list(_SOURCES)}")
    if key in ("monitor", "status_interval_seconds"):
        return (isinstance(value, int) and not isinstance(value, bool) and value >= 1, "must be a whole number >= 1")
    if isinstance(default, list):
        return (isinstance(value, list) and all(isinstance(v, str) for v in value), "must be a list of strings")
    if key == "combined_status_format":
        if not isinstance(value, str):
            return False, "must be text"
        try:
            value.format(certain="1", approximate="2")
        except (KeyError, IndexError, ValueError):
            return False, "may only use the placeholders {certain} and {approximate}"
        return True, ""
    if isinstance(default, str):
        return (isinstance(value, str) and value.strip() != "", "must be non-empty text")
    return True, ""


def load_config(path=None, overrides=None):
    """
    -> (config dict, description of where it came from, list of warning strings).
    `overrides` is {(section, key): value} from the command line; only given values are applied.
    """
    cfg = {section: dict(values) for section, values in DEFAULTS.items()}
    warnings = []
    explicit = path is not None
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    origin = "built-in defaults"

    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            origin = str(path)
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as error:
            warnings.append(f"{path}: cannot be read ({error}); using ALL built-in defaults")
            data = {}
        for section, values in data.items():
            if section not in DEFAULTS or not isinstance(values, dict):
                warnings.append(f"{path}: unknown section [{section}] ignored (typo?)")
                continue
            for key, value in values.items():
                if key not in DEFAULTS[section]:
                    warnings.append(f"{path}: unknown key '{key}' in [{section}] ignored (typo?)")
                    continue
                ok, problem = _check(section, key, value)
                if ok:
                    cfg[section][key] = value
                else:
                    warnings.append(f"{path}: [{section}] {key} = {value!r} {problem}; using default {DEFAULTS[section][key]!r}")
    elif explicit:
        warnings.append(f"{path}: config file not found; using built-in defaults")

    for (section, key), value in (overrides or {}).items():
        if value is None:
            continue
        ok, problem = _check(section, key, value)
        if ok:
            cfg[section][key] = value
        else:
            warnings.append(f"command line: {key} = {value!r} {problem}; keeping {cfg[section][key]!r}")
    return cfg, origin, warnings
