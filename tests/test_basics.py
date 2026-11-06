"""
Basic checks for the user-facing plumbing (no video needed). Run:   python tests/test_basics.py
(also works under pytest if you have it).
"""

import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "src"))   # run without installing

import json
import tempfile
from pathlib import Path

from fortnite_chest_counter import counter as chest_counter
from fortnite_chest_counter import settings
from fortnite_chest_counter.settings import DEFAULTS, format_count, load_config


def write(tmp, text):
    path = Path(tmp) / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_format_count():
    assert format_count(0) == "0"
    assert format_count(999) == "999"
    assert format_count(1000) == "1,000"
    assert format_count(1232) == "1,232"
    assert format_count(12500) == "12,500"
    assert format_count(1000000) == "1,000,000"
    assert format_count(1234567) == "1,234,567"
    assert format_count(1232, thousands=False) == "1232"      # separator switched off -> raw integer


def test_missing_config_uses_defaults():
    import os
    cfg, origin, warnings = load_config(Path(tempfile.gettempdir()) / "definitely_not_here" / "config.toml")
    assert cfg == DEFAULTS and origin == "built-in defaults"
    assert len(warnings) == 1                                   # an explicitly named file that is missing is noted...
    with tempfile.TemporaryDirectory() as tmp:                  # ...but having no config.toml at all is not an error
        here = os.getcwd()
        os.chdir(tmp)
        try:
            cfg, origin, warnings = load_config(None)
        finally:
            os.chdir(here)
    assert cfg == DEFAULTS and warnings == [] and origin == "built-in defaults"


def test_partial_config_fills_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        cfg, origin, warnings = load_config(write(tmp, '[display]\ncertain_label = "CONFIRMED"\n[detector]\nprocess_fps = 10\n'))
    assert warnings == []
    assert cfg["display"]["certain_label"] == "CONFIRMED"
    assert cfg["display"]["approximate_label"] == DEFAULTS["display"]["approximate_label"]     # untouched field
    assert cfg["detector"]["process_fps"] == 10
    assert cfg["detector"]["languages"] == DEFAULTS["detector"]["languages"]
    assert cfg["state"] == DEFAULTS["state"] and cfg["live"] == DEFAULTS["live"]               # untouched sections


def test_cli_overrides_config():
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "[detector]\nprocess_fps = 10\n")
        cfg, _, warnings = load_config(path, {("detector", "process_fps"): 20, ("state", "path"): None})
    assert warnings == [] and cfg["detector"]["process_fps"] == 20                             # CLI wins
    assert cfg["state"]["path"] == DEFAULTS["state"]["path"]                                   # an unset CLI option changes nothing
    cfg, _, warnings = load_config(None, {("detector", "process_fps"): 999})
    assert cfg["detector"]["process_fps"] == 15 and warnings                                   # bad CLI value: warn, keep


def test_invalid_config_warns_not_crashes():
    bad = ('[detector]\nprocess_fps = "fast"\ncertain_min_tier = "MAYBE"\nprocess_fpss = 5\n'
           '[display]\ncombined_status_format = "{nope}"\nuse_thousands_separator = "yes"\n[colors]\nx = 1\n')
    with tempfile.TemporaryDirectory() as tmp:
        cfg, _, warnings = load_config(write(tmp, bad))
    text = "\n".join(warnings)
    assert cfg == DEFAULTS                                      # every bad value fell back to its default
    for needle in ("process_fps", "certain_min_tier", "process_fpss", "combined_status_format",
                   "use_thousands_separator", "[colors]"):
        assert needle in text, f"expected a warning mentioning {needle}"
    with tempfile.TemporaryDirectory() as tmp:                  # not even valid TOML: all defaults + one warning
        cfg, _, warnings = load_config(write(tmp, "this is [not toml"))
    assert cfg == DEFAULTS and len(warnings) == 1


def test_obs_files_use_the_formatter_and_state_stays_integer():
    state = chest_counter.fresh_state()
    state["certain"], state["approximate"] = 1232, 1247
    with tempfile.TemporaryDirectory() as tmp:
        chest_counter.write_obs_files(state, tmp, DEFAULTS["display"])
        assert (Path(tmp) / "certain_chests.txt").read_text(encoding="utf-8") == "CERTAIN OPENED CHESTS: 1,232\n"
        assert (Path(tmp) / "approximate_chests.txt").read_text(encoding="utf-8") == "APPROX. OPENED CHESTS: 1,247\n"
        assert (Path(tmp) / "chest_status.txt").read_text(encoding="utf-8") == "1,232 certain • ~1,247 estimated\n"
        plain = dict(DEFAULTS["display"], use_thousands_separator=False)
        chest_counter.write_obs_files(state, tmp, plain)
        assert (Path(tmp) / "certain_chests.txt").read_text(encoding="utf-8") == "CERTAIN OPENED CHESTS: 1232\n"
        path = Path(tmp) / "state.json"
        chest_counter.save_state(path, state)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["certain"] == 1232 and isinstance(saved["certain"], int)                  # integers, never "1,232"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} checks passed")
