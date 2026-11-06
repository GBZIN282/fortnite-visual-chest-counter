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
        "show": "both",                         # what obs_output/chest_counter.txt shows: both | certain | approx
        "both_layout": "stacked",               # show = "both": "stacked" (two lines) or "inline" (one line = combined_status_format)
        "certain_text": "CERTAIN OPENED CHESTS: {count}",
        "approx_text": "APPROX. OPENED CHESTS: {count}",
        "combined_status_format": "{certain} certain • ~{approximate} estimated",
        "use_thousands_separator": True,
        # v0.1.0 names, still understood: a config that sets only these gets "<label>: {count}" as its text.
        "certain_label": "CERTAIN OPENED CHESTS",
        "approximate_label": "APPROX. OPENED CHESTS",
    },
    "console": {
        "verbosity": "normal",                  # minimal | normal | debug
        "colors": True,                         # coloured live window (automatically off when not a console)
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
SHOW_MODES = ("both", "certain", "approx")
BOTH_LAYOUTS = ("stacked", "inline")
VERBOSITY_LEVELS = ("minimal", "normal", "debug")
TEXT_TEMPLATES = ("certain_text", "approx_text", "combined_status_format")
# Placeholders every display text may use. {count} = this text's own number (CERTAIN for certain_text, APPROX for
# approx_text); {certain} and {approx} (or {approximate}) = either number, anywhere.
_SAMPLE = {"count": "1", "certain": "1", "approx": "2", "approximate": "2"}


def format_count(value, thousands=True):
    """The ONE place counts become text: 0, 999, 1,000, 1,234,567 (or raw integers if disabled)."""
    value = int(value)
    return f"{value:,}" if thousands else str(value)


def render_text(template, fallback, count=0, certain=0, approx=0, thousands=True):
    """Fill a user's display text. A broken template never raises: the default text is used instead."""
    values = {"count": format_count(count, thousands), "certain": format_count(certain, thousands),
              "approx": format_count(approx, thousands), "approximate": format_count(approx, thousands)}
    try:
        return str(template).format(**values)
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        return fallback.format(**values)


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
    if key == "show":
        return (value in SHOW_MODES, f"must be one of {list(SHOW_MODES)}")
    if key == "both_layout":
        return (value in BOTH_LAYOUTS, f"must be one of {list(BOTH_LAYOUTS)}")
    if key == "verbosity":
        return (value in VERBOSITY_LEVELS, f"must be one of {list(VERBOSITY_LEVELS)}")
    if key in TEXT_TEMPLATES:
        if not isinstance(value, str):
            return False, "must be text in quotes"
        try:
            value.format(**_SAMPLE)
        except (KeyError, IndexError, ValueError):
            return False, ("may only use the placeholders {count}, {certain} and {approx} "
                           "(write {{ and }} for a literal brace)")
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
            data = tomllib.loads(path.read_text(encoding="utf-8-sig"))   # utf-8-sig: Notepad/PowerShell may add a BOM
            origin = str(path)
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as error:
            warnings.append(f"{path}: cannot be read ({error}); using ALL built-in defaults")
            data = {}
        explicit_keys = {(sec, key) for sec, vals in data.items() if isinstance(vals, dict) for key in vals}
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
        # v0.1.0 configs: a custom certain_label / approximate_label still changes the overlay text.
        for label_key, text_key in (("certain_label", "certain_text"), ("approximate_label", "approx_text")):
            if (("display", label_key) in explicit_keys and ("display", text_key) not in explicit_keys
                    and cfg["display"][label_key] != DEFAULTS["display"][label_key]):
                label = cfg["display"][label_key].replace("{", "{{").replace("}", "}}")
                cfg["display"][text_key] = label + ": {count}"
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
