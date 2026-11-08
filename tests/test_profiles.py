"""
Count profiles (v0.2.2): separate saved counts per person, one profile counting at a time (profiles.py), the command
line's --profile / `profiles`, and the desktop app's profile row.        Run:   python tests/test_profiles.py   (or pytest)
"""

import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "src"))   # run without installing

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fortnite_chest_counter import counter as C
from fortnite_chest_counter import paths, profiles, settings


def _cfg(tmp):
    cfg, _, _ = settings.load_config(None, {("state", "path"): str(Path(tmp) / "state" / "chest_state.json"),
                                            ("state", "obs_dir"): str(Path(tmp) / "obs_output"),
                                            ("logging", "dir"): str(Path(tmp) / "logs")})
    return cfg


def _base(tmp):
    return Path(tmp) / "state" / "chest_state.json"


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def test_no_registry_means_only_the_default_profile_and_reading_creates_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        entry = profiles.apply(cfg)
        assert entry["id"] == "default" and entry["name"] == "Default"
        assert Path(cfg["state"]["path"]) == _base(tmp)                     # the pre-v0.2.2 counter file, unchanged
        assert not profiles.registry_path(_base(tmp)).exists()
        profiles.remember_source(_base(tmp), "default", {"source": "obs-camera"})
        assert not profiles.registry_path(_base(tmp)).exists()              # no file just for the Default profile
        before = dict(cfg)
        profiles.apply(cfg)                                                 # idempotent
        assert cfg["state"]["path"] == before["state"]["path"]


def test_existing_counts_stay_in_the_default_profile_after_the_update():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        _quiet(C.set_counts, cfg, 12, 30)                                   # counted with v0.2.1
        profiles.create(_base(tmp), "Thiefs")
        profiles.set_active(_base(tmp), "default")
        cfg = _cfg(tmp)
        profiles.apply(cfg)
        assert C.load_state(cfg["state"]["path"])["approximate"] == 30


def test_each_profile_has_its_own_counts_and_obs_shows_the_active_one():
    with tempfile.TemporaryDirectory() as tmp:
        base = _base(tmp)
        cfg = _cfg(tmp)
        profiles.apply(cfg)
        _quiet(C.set_counts, cfg, 1, 5)                                     # Default: 1 / 5
        thiefs = profiles.create(base, "Thiefs")                            # new and active, at 0
        assert thiefs["id"] == "thiefs"
        cfg = _cfg(tmp)
        profiles.apply(cfg)
        assert Path(cfg["state"]["path"]) == base.parent / "profiles" / "thiefs.json"
        assert C.load_state(cfg["state"]["path"])["approximate"] == 0
        _quiet(C.set_counts, cfg, 2, 7)                                     # Thiefs: 2 / 7
        overlay = Path(tmp) / "obs_output" / "chest_counter.txt"
        assert "7" in overlay.read_text(encoding="utf-8")
        profiles.set_active(base, "default")
        cfg = _cfg(tmp)
        profiles.apply(cfg)
        session = C.CounterSession(cfg)
        assert (session.state["certain"], session.state["approximate"]) == (1, 5)   # untouched by Thiefs' counting
        session.write_obs()
        assert "5" in overlay.read_text(encoding="utf-8") and "7" not in overlay.read_text(encoding="utf-8")
        cfg = _cfg(tmp)
        profiles.apply(cfg, "THIEFS")                                       # by name, any case, for one run
        assert C.load_state(cfg["state"]["path"])["approximate"] == 7
        assert profiles.load(base)["active"] == "default"                   # a one-run choice does not switch


def test_names_are_checked_and_ids_are_safe_file_names():
    with tempfile.TemporaryDirectory() as tmp:
        base = _base(tmp)
        for bad, why in (("", "Type a name"), ("   ", "Type a name"), ("x" * 41, "at most 40"), ("a\tb\x07", "cannot be shown")):
            try:
                profiles.create(base, bad)
                raise AssertionError(f"accepted {bad!r}")
            except profiles.ProfileError as error:
                assert why in str(error), error
        profiles.create(base, "Thiefs")
        try:
            profiles.create(base, "  thiefs ")
            raise AssertionError("duplicate accepted")
        except profiles.ProfileError as error:
            assert "already a profile" in str(error)
        assert profiles.slug("João Ação") == "joao-acao"
        assert profiles.slug("CON") == "p-con" and profiles.slug("deleted") == "p-deleted"
        assert profiles.slug("Default") == "p-default"
        assert profiles.slug("!!!") == "profile" and profiles.slug("Ninja", {"ninja"}) == "ninja-2"
        e = profiles.create(base, "Thiefs 2")
        assert e["id"] == "thiefs-2" and e["name"] == "Thiefs 2"
        assert profiles.create(base, "  Big   Gap ")["name"] == "Big Gap"
        family = profiles.create(base, "\U0001F468‍\U0001F469‍\U0001F467 squad")     # emoji with joiners
        assert family["id"] == "squad" and "‍" in family["name"]
        names = [p["name"] for p in profiles.load(base)["profiles"]]
        assert names == ["Default", "Thiefs", "Thiefs 2", "Big Gap", family["name"]]


def test_a_new_profile_never_overwrites_a_counter_file_left_on_disk():
    with tempfile.TemporaryDirectory() as tmp:
        base = _base(tmp)
        left = base.parent / "profiles" / "thiefs.json"
        left.parent.mkdir(parents=True)
        left.write_text(json.dumps({"certain": 3, "approximate": 9}), encoding="utf-8")
        e = profiles.create(base, "Thiefs")
        assert e["id"] == "thiefs-2" and json.loads(left.read_text(encoding="utf-8"))["approximate"] == 9


def test_rename_keeps_the_counts_and_delete_keeps_a_backup():
    with tempfile.TemporaryDirectory() as tmp:
        base = _base(tmp)
        profiles.create(base, "Thiefs")
        cfg = _cfg(tmp)
        profiles.apply(cfg)
        _quiet(C.set_counts, cfg, 4, 6)
        profiles.rename(base, "thiefs", "Thiefs (Twitch)")
        reg = profiles.load(base)
        assert profiles.active(reg)["name"] == "Thiefs (Twitch)" and profiles.active(reg)["id"] == "thiefs"
        cfg = _cfg(tmp)
        profiles.apply(cfg)
        assert C.load_state(cfg["state"]["path"])["approximate"] == 6
        try:
            profiles.delete(base, "default")
            raise AssertionError("deleted the Default profile")
        except profiles.ProfileError:
            pass
        moved = profiles.delete(base, "thiefs")
        assert moved.parent == base.parent / "profiles" / "deleted" and json.loads(moved.read_text(encoding="utf-8"))["approximate"] == 6
        reg = profiles.load(base)
        assert reg["active"] == "default" and [p["id"] for p in reg["profiles"]] == ["default"]


def test_a_damaged_profile_list_is_rebuilt_from_the_counter_files():
    with tempfile.TemporaryDirectory() as tmp:
        base = _base(tmp)
        profiles.create(base, "Thiefs")
        profiles.create(base, "Replays")
        reg_path = profiles.registry_path(base)
        reg_path.write_text("{ not json", encoding="utf-8")
        warnings = []
        reg = profiles.load(base, warn=warnings.append)
        assert [p["id"] for p in reg["profiles"]] == ["default", "replays", "thiefs"] and reg["active"] == "default"
        assert warnings and "No counts were lost" in warnings[0]
        assert list(base.parent.glob("profiles.damaged-*.json"))            # the bad file is kept for inspection
        assert json.loads(reg_path.read_text(encoding="utf-8"))["profiles"]  # and a good one written
        reg_path.write_text(json.dumps({"version": 1, "active": "gone", "profiles": [{"id": "thiefs", "name": "T"}]}),
                            encoding="utf-8")
        reg = profiles.load(base)
        assert reg["active"] == "default" and [p["id"] for p in reg["profiles"]] == ["default", "thiefs"]
        reg_path.write_text(json.dumps({"profiles": [{"id": "..\\..\\evil", "name": "x"}]}), encoding="utf-8")
        reg = profiles.load(base, warn=warnings.append)                     # an id must be a plain file name
        assert all(p["id"] in ("default", "replays", "thiefs") for p in reg["profiles"])


def test_the_remembered_source_is_cleaned_and_saved_only_on_change():
    with tempfile.TemporaryDirectory() as tmp:
        base = _base(tmp)
        profiles.create(base, "Thiefs")
        profiles.remember_source(base, "thiefs", {"source": "stream", "url": " https://www.twitch.tv/thiefs ",
                                                  "stream_stability": "maximum", "monitor": True, "junk": 1})
        src = profiles.active(profiles.load(base))["source"]
        assert src == {"source": "stream", "url": "https://www.twitch.tv/thiefs", "stream_stability": "maximum"}
        before = profiles.registry_path(base).stat().st_mtime_ns
        profiles.remember_source(base, "thiefs", dict(src))
        assert profiles.registry_path(base).stat().st_mtime_ns == before


def test_command_line_uses_the_active_profile_and_explicit_state_files_stay_as_given():
    with tempfile.TemporaryDirectory() as tmp:
        here, app_dir = os.getcwd(), paths.APP_DIR
        os.chdir(tmp)
        paths.APP_DIR = Path(tmp)                                           # main() runs from the program folder
        try:
            profiles.create(Path("state/chest_state.json"), "Thiefs")
            args = SimpleNamespace(config=None, state=None, profile=None)
            cfg, _ = C.make_config(args)
            assert Path(cfg["state"]["path"]) == Path("state/profiles/thiefs.json") and C.profile_label(cfg) == "Thiefs"
            cfg, _ = C.make_config(SimpleNamespace(config=None, state=None, profile="Default"))
            assert Path(cfg["state"]["path"]) == Path("state/chest_state.json")
            cfg, _ = C.make_config(SimpleNamespace(config=None, state="x/s.json", profile=None))
            assert cfg["state"]["path"] == "x/s.json" and C.profile_label(cfg) is None
            for bad in (SimpleNamespace(config=None, state=None, profile="Nobody"),
                        SimpleNamespace(config=None, state="x/s.json", profile="Thiefs")):
                try:
                    C.make_config(bad)
                    raise AssertionError("accepted")
                except C.UserError:
                    pass
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                assert C.main(["profiles", "--activate", "default"]) == 0
                assert C.main(["show"]) == 0
            text = out.getvalue()
            assert "* Default" in text and "  Thiefs" in text and "profile Default" in text
        finally:
            os.chdir(here)
            paths.APP_DIR = app_dir


def _qt():
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return None
    return QApplication.instance() or QApplication([])


def test_app_profile_row_switches_counts_obs_text_and_source():
    qt = _qt()
    if qt is None:
        print("      (skipped: PySide6 not installed)")
        return
    from fortnite_chest_counter.gui import app as A
    here, app_dir = os.getcwd(), paths.APP_DIR
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        paths.APP_DIR = Path(tmp)
        win = None
        try:
            win = A.MainWindow()
            win.timer.stop()
            win.slow.stop()
            win._source_scan.join(30)
            win._fill_sources([], [])                                       # what the finished device scan does
            d = win.dashboard
            assert d.profile.count() == 1 and d.profile.currentText() == "Default" and not d.profile_delete.isEnabled()
            assert win.windowTitle() == A.APP_NAME
            win._set(3, 8, "set_count")
            base = Path(tmp) / "state" / "chest_state.json"
            profiles.create(base, "Thiefs", activate=False)
            profiles.remember_source(base, "thiefs", {"source": "stream", "url": "https://www.twitch.tv/thiefs"})
            win.fill_profiles()
            assert d.profile.count() == 2 and d.profile.currentText() == "Default"
            d.profile.setCurrentIndex(1)
            win.switch_profile(1)                                            # what choosing it in the list does
            assert profiles.load(base)["active"] == "thiefs" and win.counts == (0, 0)
            assert d.url.text() == "https://www.twitch.tv/thiefs" and (d.source.currentData() or {}).get("source") == "stream"
            assert "Thiefs" in win.windowTitle() and d.profile_delete.isEnabled()
            overlay = (Path(tmp) / "obs_output" / "chest_counter.txt").read_text(encoding="utf-8")
            assert "8" not in overlay                                       # OBS follows the selected profile
            win._set(1, 2, "set_count")
            assert C.load_state(base)["approximate"] == 8                   # Default untouched
            d.profile.setCurrentIndex(0)
            win.switch_profile(0)
            assert win.counts == (3, 8)
            win.set_mode("counting")                                        # no profile changes while counting
            assert not d.profile.isEnabled() and not d.profile_new.isEnabled() and not d.profile_delete.isEnabled()
            win.set_mode("stopped")
            assert d.profile.isEnabled()
        finally:
            if win is not None:
                if win._source_scan is not None:
                    win._source_scan.join(30)
                win.preview_reader and win.preview_reader.close()
                win.deleteLater()
            qt.processEvents()
            os.chdir(here)
            paths.APP_DIR = app_dir


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except Exception:
            failed += 1
            import traceback
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} profile checks passed")
    sys.exit(1 if failed else 0)
