"""
The app's optional OBS WebSocket overlay output.

It mirrors obs_output/chest_counter.txt - THE overlay file, whoever wrote it (the counting worker, the app's Edit counts /
Reset / Overlay page, the console commands) - into one OBS Text source. Copying the file, instead of formatting the
numbers a second time, guarantees viewers see exactly the same text either way, and the text file stays what it always
was: always written, the source of truth.

Everything happens in one background thread of the app: OBS being closed, slow, restarting or misconfigured can never
block the window or the counting worker (a separate process that does not know this exists). Only the newest text is
ever sent - nothing queues up while OBS is away.
"""

import os
import threading
import time
from pathlib import Path

from fortnite_chest_counter.obs import client as obs

BACKOFF_SECONDS = (2, 4, 8, 15, 30)
POLL_SECONDS = 0.2                      # how often the file is checked (and how long OBS events are waited for)
RECHECK_SECONDS = 10                    # re-check "Read from file" (older OBS sends no InputSettingsChanged event)
CONNECTION_KEYS = ("enabled", "host", "port", "password")


def read_overlay(path):
    """The overlay text as OBS should show it (the file without its final line break), or None if not written yet."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return text[:-1] if text.endswith("\n") else text


def _signature(path):
    try:
        st = os.stat(path)
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


def same_file(a, b):
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (TypeError, ValueError):
        return False


class TextOutputLink:
    """Start with start(), feed settings with configure(); the window reads status() and sends commands."""

    def __init__(self, client_factory=obs.ObsClient):
        self._client_factory = client_factory
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._settings = None
        self._connection_gen = 0                # +1: drop the connection and connect again with the new settings
        self._target_gen = 0                    # +1: same connection, pick the source again
        self._hold = False                      # wrong password / kicked / unsupported: wait for the user
        self._commands = []
        self._stopped = False
        self._status = {"state": "off", "message": "", "obs": "", "sources": [], "source": "", "uuid": "",
                        "updates": 0, "text": None}
        self.version = 0
        self._thread = None

    # ---- called from the window (any thread)
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="obs-text-output")
            self._thread.start()
        return self

    def configure(self, enabled, host, port, password, source, source_uuid, overlay_file):
        new = {"enabled": bool(enabled), "host": str(host), "port": int(port), "password": password or "",
               "source": source or "", "source_uuid": source_uuid or "", "overlay_file": str(overlay_file)}
        with self._lock:
            old, self._settings = self._settings, new
            if old is None or any(old[k] != new[k] for k in CONNECTION_KEYS):
                self._connection_gen += 1
                self._hold = False
            elif any(old[k] != new[k] for k in ("source", "source_uuid", "overlay_file")):
                self._target_gen += 1
        self._wake.set()

    def reconnect(self):
        """The Connect button: try again now, also after a wrong password or a kick."""
        with self._lock:
            self._connection_gen += 1
            self._hold = False
        self._wake.set()

    def refresh_sources(self):
        self._command("sources")

    def use_direct_updates(self):
        self._command("direct")

    def status(self):
        with self._lock:
            return self.version, dict(self._status)

    def stop(self, timeout=1.0):
        self._stopped = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    # ---- the thread
    def _command(self, name):
        with self._lock:
            self._commands.append(name)
        self._wake.set()

    def _publish(self, **changes):
        with self._lock:
            self._status = {**self._status, **changes}
            self.version += 1

    def _sleep(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()

    def _run(self):
        attempt = 0
        while not self._stopped:
            with self._lock:
                s, gen, hold = self._settings, self._connection_gen, self._hold
            if not s or not s["enabled"]:
                self._publish(state="off", message="OBS reads the text file as usual.", obs="", sources=[])
                self._sleep(None)
                continue
            if hold:
                self._sleep(None)
                continue
            self._publish(state="connecting", message=f"Connecting to OBS at {s['host']}:{s['port']} ...")
            client = self._client_factory(s["host"], s["port"], s["password"])
            try:
                client.connect()
                attempt = 0
                self._session(client, gen)
            except (obs.ObsAuthFailed, obs.ObsKicked, obs.ObsUnsupported) as error:
                state = ("password" if isinstance(error, obs.ObsAuthFailed) else
                         "kicked" if isinstance(error, obs.ObsKicked) else "unsupported")
                with self._lock:
                    if self._connection_gen == gen:
                        self._hold = True
                self._publish(state=state, message=str(error), obs="", sources=[])
            except obs.ObsError as error:
                delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                attempt += 1
                self._publish(state="waiting", message=f"{error} Trying again in {delay} s.", obs="")
                self._sleep(delay)
            except Exception as error:                      # never let a surprise end the thread
                delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                attempt += 1
                self._publish(state="error", message=f"Unexpected problem ({type(error).__name__}: {error}). "
                                                     f"Trying again in {delay} s.", obs="")
                self._sleep(delay)
            finally:
                client.close()

    def _resolve(self, client, sources, s):
        """-> (source or None, mode) where mode is live | reads_file | pick | missing; publishes the state."""
        target = obs.find_source(sources, s["source"], s["source_uuid"])
        if target is None:
            if not s["source"]:
                self._publish(state="pick", message="Connected. Pick the OBS Text source the app should update.",
                              source="", uuid="")
                return None, "pick"
            self._publish(state="missing", message=f'Connected, but OBS has no Text source called "{s["source"]}". '
                                                   "Pick one (Refresh lists them).", source="", uuid="")
            return None, "missing"
        try:
            on, path = obs.reads_file(client, target)
        except obs.ObsRequestFailed as error:
            if error.code == obs.RESOURCE_NOT_FOUND:
                self._publish(state="missing", message=f'The Text source "{target["name"]}" is gone. Pick another one.',
                              source="", uuid="")
                return None, "missing"
            raise
        if on:
            if same_file(path, s["overlay_file"]):
                message = (f'"{target["name"]}" already shows the counter by reading the text file (OBS re-reads it about '
                           'once a second). Click "Use direct updates" for instant changes, or keep it like this.')
            else:
                message = (f'"{target["name"]}" has "Read from file" ticked ({path or "no file chosen"}), so OBS ignores '
                           'direct updates. Click "Use direct updates" to switch it, or pick another source.')
            self._publish(state="reads_file", message=message, source=target["name"], uuid=target["uuid"])
            return target, "reads_file"
        self._publish(state="live", message=f'Updating "{target["name"]}" in OBS.', source=target["name"],
                      uuid=target["uuid"])
        return target, "live"

    @staticmethod
    def _matches(target, data):
        if target is None:
            return False
        if target["uuid"] and data.get("inputUuid"):
            return data["inputUuid"] == target["uuid"]
        return target["name"] in (data.get("inputName"), data.get("oldInputName"))

    def _session(self, client, gen):
        sources = obs.list_text_sources(client)
        self._publish(obs=client.version_text, sources=sources)
        target, mode, target_gen = None, None, None
        sent, file_sig, next_check = None, None, 0.0
        while not self._stopped:
            with self._lock:
                if self._connection_gen != gen or not self._settings["enabled"]:
                    return
                s, tgen = self._settings, self._target_gen
                commands, self._commands = self._commands, []
            if tgen != target_gen:                          # first time, or the user picked another source
                target_gen = tgen
                target, mode = self._resolve(client, sources, s)
                sent = None
            for command in commands:
                if command == "sources":
                    sources = obs.list_text_sources(client)
                    self._publish(sources=sources)
                    if target is None:
                        target, mode = self._resolve(client, sources, s)
                        sent = None
                elif command == "direct" and target is not None and mode == "reads_file":
                    text = read_overlay(s["overlay_file"]) or ""
                    obs.use_direct_updates(client, target, text)
                    target, mode = self._resolve(client, sources, s)
                    sent = text if mode == "live" else None
            if mode == "live":
                sig = _signature(s["overlay_file"])
                if sent is None or sig != file_sig:
                    file_sig = sig
                    text = read_overlay(s["overlay_file"])
                    if text is not None and text != sent:
                        obs.set_text(client, target, text)
                        sent = text
                        with self._lock:
                            updates = self._status["updates"] + 1
                        self._publish(updates=updates, text=text, message=f'Updating "{target["name"]}" in OBS.')
            elif mode == "reads_file" and time.monotonic() >= next_check:
                next_check = time.monotonic() + RECHECK_SECONDS
                target, mode = self._resolve(client, sources, s)
                sent = None
            # OBS events; this is also the pause between two file checks
            for event in client.poll(POLL_SECONDS):
                kind, data = event.get("eventType"), event.get("eventData") or {}
                if kind == "ExitStarted":
                    raise obs.ObsDisconnected("OBS is closing.")
                if kind in ("InputCreated", "InputRemoved", "InputNameChanged"):
                    sources = obs.list_text_sources(client)
                    self._publish(sources=sources)
                if kind == "InputNameChanged" and self._matches(target, data):
                    target = {**target, "name": data.get("inputName", target["name"])}
                    self._publish(source=target["name"], uuid=target["uuid"],
                                  message=(f'Updating "{target["name"]}" in OBS.' if mode == "live" else
                                           self._status["message"]))
                elif kind == "InputRemoved" and self._matches(target, data):
                    self._publish(state="missing", message=f'The Text source "{target["name"]}" was deleted in OBS. '
                                                           "Pick another one.", source="", uuid="")
                    target, mode, sent = None, "missing", None
                elif kind == "InputCreated" and target is None:
                    target, mode = self._resolve(client, sources, s)
                    sent = None
                elif kind == "InputSettingsChanged" and self._matches(target, data):
                    target, mode = self._resolve(client, sources, s)
                    sent = None
