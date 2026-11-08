"""
Live frame sources. Every source yields (seconds_since_start, 1280x720 RGB uint8 frame) with
LATEST-FRAME semantics: if the detector is slower than the source, old frames are dropped
(and counted), never queued, so latency cannot grow.

How: ffmpeg (already a requirement) opens the video input, scales it to 1280x720 and reduces it
to the detector cadence; a reader thread keeps draining its pipe and stores only the newest
frame. No new Python dependency, no frames written to disk.

Backends (all passive pixel capture: nothing touches Fortnite, nothing runs on the gaming PC):

  obs-camera  OBS Virtual Camera (DirectShow). RECOMMENDED for single-PC and dual-PC setups:
              OBS shows a clean gameplay-only scene ("ChestDetectorFeed") as a virtual webcam.
  device      any DirectShow video device by name, e.g. a capture card opened directly. Advanced:
              some card drivers refuse a second reader while OBS holds the device.
  desktop     screen capture (gdigrab) of one monitor. Fallback for single-PC users: alt-tab,
              covering windows, resolution changes and overlays all corrupt what the detector sees.
  window      one window, captured with Windows Graphics Capture (FFmpeg `gfxcapture`): meant for an OBS
              "Windowed Projector (Source)" of the gameplay source. For streamers whose capture card is owned by
              OBS and whose Virtual Camera is used by another app. The window may sit behind other windows; a
              minimised window only gives black pictures, so it is watched and the user is told.
  file        a video file played in real time. For testing the live pipeline without a device.
"""

import queue
import re
import subprocess
import sys
import threading
import time
from collections import deque

import numpy as np

from fortnite_chest_counter import paths
from fortnite_chest_counter.detection import visual as V

WIDTH, HEIGHT = V.NORMALIZED_WIDTH, V.NORMALIZED_HEIGHT
FRAME_BYTES = WIDTH * HEIGHT * 3


def list_video_devices():
    """DirectShow video devices as [(name, kind)], kind in video/audio/none."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                         capture_output=True, stdin=paths.child_stdin(), creationflags=paths.child_process_flags())
    out = out.stderr.decode("utf-8", errors="replace")
    return [(m[1], m[2]) for m in re.finditer(r'"([^"]+)" \((video|audio|none)\)', out)
            if "Alternative name" not in m[0]]


def list_monitors():
    """Monitors as [(x, y, width, height)] in physical pixels (Windows)."""
    import ctypes
    from ctypes import wintypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    monitors = []
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(_monitor, _dc, rect, _data):
        r = rect.contents
        monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(0, 0, proc_type(callback), 0)
    return monitors


class LiveSource:
    def __init__(self, label, input_args, fps):
        self.label, self.input_args, self.fps = label, list(input_args), fps
        self.info = {"input_resolution": None, "input_fps": None}
        self._process, self._thread, self._err_thread = None, None, None
        self._cond = threading.Condition()
        self._latest, self._seq, self._eof, self._stop = None, 0, False, False
        self._t0 = None
        self.frames_read = 0
        self.frames_processed = 0
        self.frames_dropped = 0
        self.stderr_tail = []

    # ---- lifecycle ----
    def open(self, timeout=20.0):
        cmd = (["ffmpeg", "-hide_banner", "-loglevel", "info"] + self.input_args +
               ["-vf", f"scale={WIDTH}:{HEIGHT},fps={self.fps}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
        self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=10 ** 8,
                                         stdin=paths.child_stdin(), creationflags=paths.child_process_flags())
        self._t0 = time.monotonic()
        self._err_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._err_thread.start()
        self._thread = threading.Thread(target=self._read_frames, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._latest is None and not self._eof and time.monotonic() < deadline:
                self._cond.wait(timeout=0.2)
        if self._latest is None:
            self.close()
            detail = " | ".join(self.stderr_tail[-3:]) or "no output from ffmpeg"
            raise RuntimeError(f"no frames arrived from '{self.label}' ({detail})")
        return self.info

    def request_stop(self):
        """Non-blocking: make frames() return promptly (safe to call from another thread)."""
        self._stop = True
        with self._cond:
            self._cond.notify_all()

    def close(self, wait=True):
        self._stop = True
        if self._process and self._process.poll() is None:
            self._process.terminate()
            if wait:
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
        with self._cond:
            self._cond.notify_all()

    # ---- threads ----
    def _read_stderr(self):
        for raw in self._process.stderr:
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                self.stderr_tail = (self.stderr_tail + [line])[-8:]
            if "Stream #0" in line and "Video:" in line and self.info["input_resolution"] is None:
                size = re.search(r"(\d{3,5})x(\d{3,5})", line.split("Video:")[1])
                rate = re.search(r"([\d.]+) fps", line)
                if size:
                    self.info["input_resolution"] = (int(size[1]), int(size[2]))
                if rate:
                    self.info["input_fps"] = float(rate[1])

    def _read_frames(self):
        stream = self._process.stdout
        while not self._stop:
            raw = stream.read(FRAME_BYTES)
            if len(raw) < FRAME_BYTES:
                break
            frame = np.frombuffer(raw, np.uint8).reshape(HEIGHT, WIDTH, 3)
            with self._cond:
                self._latest = (time.monotonic() - self._t0, frame)
                self._seq += 1
                self.frames_read += 1
                self._cond.notify_all()
        with self._cond:
            self._eof = True
            self._cond.notify_all()

    # ---- consumer ----
    def frames(self):
        last = 0
        while not self._stop:
            with self._cond:
                self._cond.wait_for(lambda: self._seq > last or self._eof or self._stop, timeout=1.0)
                if self._seq > last:
                    item, seq = self._latest, self._seq
                else:
                    item, seq = None, last
                    if self._eof:
                        return
            if item is not None:
                self.frames_dropped += seq - last - 1       # overwritten before the detector got to them
                self.frames_processed += 1
                last = seq
                yield item

    def elapsed(self):
        return time.monotonic() - self._t0


# ==================================================================
# WINDOW CAPTURE (an OBS projector window)
# ==================================================================

OBS_EXECUTABLES = ("obs64.exe", "obs32.exe", "obs.exe")
# Only used to list projectors first; titles are translated by OBS, so nothing depends on these words.
_PROJECTOR_WORDS = ("projector", "projetor", "proyector", "projecteur", "projektor", "proiettore", "multiview")
WINDOW_STEPS = ("  1. In OBS, right-click your gameplay source (for example the capture card) and choose\n"
                "     \"Windowed Projector (Source)\"\n"
                "  2. Leave that window open - it can stay behind other windows, but do not minimize it\n"
                "  3. In the app click Refresh and pick it in the Video source list")


def _win32():
    """(user32, kernel32) with the signatures used here, or None when not on Windows."""
    import ctypes
    from ctypes import wintypes
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return None
    for name, args, res in (("IsWindowVisible", [wintypes.HWND], wintypes.BOOL), ("IsIconic", [wintypes.HWND], wintypes.BOOL),
                            ("IsWindow", [wintypes.HWND], wintypes.BOOL),
                            ("GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int),
                            ("GetWindowTextW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
                            ("GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD)):
        getattr(user32, name).argtypes, getattr(user32, name).restype = args, res
    kernel32.OpenProcess.argtypes, kernel32.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return user32, kernel32


def _process_name(kernel32, pid):
    import ctypes
    from ctypes import wintypes
    handle = kernel32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION (works for elevated OBS)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def list_windows():
    """Visible top-level windows with a title -> [(hwnd, title, exe name in lower case, minimized)]. [] off Windows."""
    import ctypes
    from ctypes import wintypes
    api = _win32()
    if api is None:
        return []
    user32, kernel32 = api
    found = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _data):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append((int(hwnd), buf.value, _process_name(kernel32, pid.value), bool(user32.IsIconic(hwnd))))
        except Exception:
            pass                                                   # a window that vanished meanwhile
        return True

    user32.EnumWindows(proc_type(callback), 0)
    return found


def _is_obs_main_window(title):
    return re.match(r"^OBS (Studio )?\d", title) is not None   # "OBS Studio 33.0.1 - Profile: ... - Scenes: ..."


def list_obs_windows(windows=None):
    """OBS windows the counter can capture (projectors first, OBS's main window left out) -> [(title, minimized)]."""
    windows = list_windows() if windows is None else windows
    seen, out = set(), []
    for _, title, exe, minimized in windows:
        if exe in OBS_EXECUTABLES and not _is_obs_main_window(title) and title not in seen:
            seen.add(title)
            out.append((title, minimized))
    out.sort(key=lambda w: (not any(word in w[0].lower() for word in _PROJECTOR_WORDS), w[0].lower()))
    return out


def find_window(title, windows=None):
    """HWND of the visible window with exactly this title (an OBS window first), or None."""
    windows = list_windows() if windows is None else windows
    matches = [w for w in windows if w[1] == title]
    matches.sort(key=lambda w: w[2] not in OBS_EXECUTABLES)
    return matches[0][0] if matches else None


def window_state(hwnd):
    """'gone' | 'minimized' | 'hidden' | 'ok' for a window handle."""
    api = _win32()
    if api is None:
        return "ok"
    user32, _ = api
    if not user32.IsWindow(hwnd):
        return "gone"
    if user32.IsIconic(hwnd):
        return "minimized"
    if not user32.IsWindowVisible(hwnd):
        return "hidden"
    return "ok"


def window_capture_args(hwnd):
    """FFmpeg input for one window: Windows Graphics Capture (no cursor, no border), copied to normal memory, and cut to
    16:9 from the centre - an OBS projector letterboxes the picture when its window is not 16:9, and the detector needs
    the picture without bars. resize_mode=scale_aspect keeps the frame size fixed when the window is resized."""
    graph = (f"gfxcapture=hwnd={int(hwnd)}:capture_cursor=0:max_framerate=30:resize_mode=scale_aspect,"
             "hwdownload,format=bgra,crop=w='min(iw,ih*16/9)':h='min(ih,iw*9/16)'")
    return ["-f", "lavfi", "-i", graph]


class WindowSource(LiveSource):
    """A window (an OBS Windowed Projector) as a live source. Same latest-frame reader as every other source; a small
    watcher notices a closed window (FFmpeg would then wait for ever) and a minimised one (black pictures)."""

    def __init__(self, title, fps):
        super().__init__(f"window: {title}", [], fps)
        self.title, self.hwnd = title, None
        self._ended_reason = None
        self._notices = deque()

    @property
    def ended_reason(self):
        """Why the pictures stopped, for the message at the end ("was closed" also when FFmpeg noticed it first)."""
        if self._ended_reason is None and self.hwnd and window_state(self.hwnd) == "gone":
            self._ended_reason = "the projector window was closed"
        return self._ended_reason

    def open(self, timeout=20.0):
        self.hwnd = find_window(self.title)
        if not self.hwnd:
            raise RuntimeError(f'the window "{self.title}" is not open')
        if window_state(self.hwnd) == "minimized":
            raise RuntimeError(f'the window "{self.title}" is minimized')
        self.input_args = window_capture_args(self.hwnd)
        info = super().open(timeout)
        threading.Thread(target=self._watch, daemon=True, name="window-watch").start()
        return info

    def _watch(self):
        last, previous = "ok", "ok"
        while not self._stop:
            time.sleep(0.5)
            state = window_state(self.hwnd)
            if state == "gone":
                self._ended_reason = "the projector window was closed"
                self.close(wait=False)
                return
            seen, previous = previous, state
            if state != last and state == seen:             # the same for 1 s: no notice for a flicker while restoring
                if state in ("minimized", "hidden"):
                    self._notices.append(("warn", f"the projector window is {state}: the counter only sees a black picture "
                                                  "and cannot count until it is shown again (it may stay behind other "
                                                  "windows, just not minimized)."))
                elif last in ("minimized", "hidden"):
                    self._notices.append(("info", "the projector window is visible again - counting continues."))
                last = state

    def take_notices(self):
        """[(level, text)] since the last call (main loop)."""
        out = []
        while self._notices:
            out.append(self._notices.popleft())
        return out


# ==================================================================
# LIVESTREAM URL (Twitch / YouTube, read with Streamlink)
# ==================================================================

STREAM_QUALITIES = {"720p": "720p60,720p,best", "1080p": "1080p60,1080p,best", "480p": "480p,480p30,best"}


class StreamSource:
    """
    A public livestream URL (Twitch, YouTube - anything Streamlink can read), without OBS or a browser:
    Streamlink -> FFmpeg (1280x720 at the analysis rate) -> the detector.

    Unlike the local sources, EVERY decoded picture is analysed, in order: these platforms deliver video in bursts of
    several seconds, and the latest-frame reader would throw most of each burst away - chest pop-ups included. Delay does
    not matter here, completeness does. Memory stays bounded by backpressure: a small picture queue, then the pipes, then
    Streamlink's own buffer of compressed video. Timestamps are stream time (picture number / rate), not arrival time.

    If the stream drops after it started (network, stream restart), it is opened again with backoff at the newest part
    (nothing is analysed twice), the time line jumps over the missed part, and the counts are kept.
    """
    QUEUE_PICTURES = 15
    BUFFERING_AFTER = 10.0                  # seconds without pictures (bursts normally arrive every ~4-5 s)
    RECONNECT_DELAYS = (5, 10, 20, 30, 60)
    FIRST_PICTURE_TIMEOUT = 45.0

    def __init__(self, url, fps, quality="720p"):
        self.url, self.fps = url, fps
        self.quality = STREAM_QUALITIES.get(quality, quality)
        self.label = f"stream: {url}"
        self.info = {"input_resolution": None, "input_fps": None}
        self.frames_read = self.frames_processed = self.frames_dropped = 0
        self.stderr_tail = []
        self.ended_reason = None
        self._queue = queue.Queue(maxsize=self.QUEUE_PICTURES)
        self._stop = threading.Event()
        self._started = threading.Event()   # the first picture arrived, or opening failed
        self._failure = None
        self._done = False
        self._reconnecting = False
        self._procs = ()
        self._notices = deque()
        self._last_t = 0.0

    def streamlink_command(self, live_edge):
        return [sys.executable, "-m", "streamlink", "--stdout", "--loglevel", "info", "--hls-live-edge", str(live_edge),
                "--stream-segment-attempts", "5", "--stream-timeout", "30", self.url, self.quality]

    # ---- processes
    def _start(self, live_edge):
        flags = paths.child_process_flags()
        sl = subprocess.Popen(self.streamlink_command(live_edge), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, creationflags=flags)
        ff = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "info", "-i", "pipe:0", "-an",
                               "-vf", f"scale={WIDTH}:{HEIGHT},fps={self.fps}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                              stdin=sl.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=10 ** 7,
                              creationflags=flags)
        sl.stdout.close()                   # FFmpeg owns the pipe now: if it ends, Streamlink gets a broken pipe and ends too
        self._procs = (sl, ff)
        for proc, tag in ((sl, "streamlink"), (ff, "ffmpeg")):
            threading.Thread(target=self._read_log, args=(proc, tag), daemon=True).start()
        return sl, ff

    def _kill(self):
        for proc in self._procs:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass

    def _read_log(self, proc, tag):
        for raw in proc.stderr:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            self.stderr_tail = (self.stderr_tail + [f"{tag}: {line}"])[-12:]
            if tag == "ffmpeg" and "Stream #0" in line and "Video:" in line and self.info["input_resolution"] is None:
                size = re.search(r"(\d{3,5})x(\d{3,5})", line.split("Video:")[1])
                rate = re.search(r"([\d.]+) fps", line)
                if size:
                    self.info["input_resolution"] = (int(size[1]), int(size[2]))
                if rate:
                    self.info["input_fps"] = float(rate[1])
            elif tag == "streamlink" and ("advertisement" in line.lower() or "pre-roll ads" in line.lower()):
                self._notices.append(("ad", "AD BREAK on the stream - counting continues when the game is back."))

    def _error(self):
        """Streamlink's own error line ("No playable streams found ...") from the latest attempt, if any."""
        for line in reversed(self.stderr_tail):
            if line.startswith("streamlink: error: "):
                return line[len("streamlink: error: "):]
        return None

    # ---- the reader thread: every picture, in order
    def _pump(self):
        live_edge, attempt, n, gap, lost_at = 3, 0, 0, 0.0, None
        while not self._stop.is_set():
            self.stderr_tail = []
            _, ff = self._start(live_edge)
            got = 0
            while not self._stop.is_set():
                raw = ff.stdout.read(FRAME_BYTES)
                if len(raw) < FRAME_BYTES:
                    break
                if lost_at is not None:     # back after a drop: the time line jumps over the part that was not seen
                    missed = time.monotonic() - lost_at
                    gap += missed
                    lost_at, self._reconnecting = None, False
                    self._notices.append(("live", "RECONNECTED - video resumed, counting continues (counts kept)."))
                    self._notices.append(("incomplete", f"about {missed:.0f} s of the stream could not be seen: chests "
                                                        "opened in that part are missing from the count."))
                t = gap + n / self.fps
                n, got = n + 1, got + 1
                item = (t, np.frombuffer(raw, np.uint8).reshape(HEIGHT, WIDTH, 3))
                while not self._stop.is_set():
                    try:
                        self._queue.put(item, timeout=0.5)      # blocks while the detector catches up (backpressure)
                        break
                    except queue.Full:
                        pass
                self.frames_read += 1
                self._started.set()
            self._kill()
            if self._stop.is_set():
                break
            reason = self._error() or "the stream ended or the connection dropped"
            if n == 0:                      # never got a picture: report it instead of retrying for ever
                self._failure = reason
                self._started.set()
                break
            attempt = 1 if got else attempt + 1
            delay = self.RECONNECT_DELAYS[min(attempt, len(self.RECONNECT_DELAYS)) - 1]
            if lost_at is None:
                lost_at = time.monotonic()
            self._reconnecting = True
            if "No playable streams" in reason:
                self._notices.append(("offline", f"STREAM OFFLINE ({reason}). Checking again in {delay} s - your counts "
                                                 "are kept."))
            else:
                self._notices.append(("reconnecting", f"CONNECTION LOST ({reason}). Reconnecting in {delay} s - your "
                                                      "counts are kept."))
            self._stop.wait(delay)
            live_edge = 1                   # newest part only: nothing already analysed comes again
        self._done = True

    # ---- the LiveSource interface
    def open(self, timeout=20.0):
        threading.Thread(target=self._pump, daemon=True, name="stream-pump").start()
        if not self._started.wait(max(timeout, self.FIRST_PICTURE_TIMEOUT)):
            detail = " | ".join(self.stderr_tail[-3:])
            self.close()
            raise RuntimeError(f"no video arrived from the stream within {self.FIRST_PICTURE_TIMEOUT:.0f} s"
                               + (f" ({detail})" if detail else ""))
        if self._failure:
            self.close()
            raise RuntimeError(self._failure)
        return self.info

    @staticmethod
    def _say(state, text):
        """live | buffering | ad | incomplete | reconnecting | offline. The app colours these (green / yellow / red) and
        shows the non-live ones over the preview; the console prints them as info / warning / error lines."""
        from fortnite_chest_counter.console import CONSOLE
        if CONSOLE.machine:
            CONSOLE.emit("stream", state=state, text=text)
        elif state in ("reconnecting", "offline"):
            CONSOLE.error(text)
        elif state == "live":
            CONSOLE.info(text)
        else:
            CONSOLE.warn(text)

    def frames(self):
        last, buffering = time.monotonic(), False             # notices are printed here, in the counting thread
        while not self._stop.is_set():
            while self._notices:
                self._say(*self._notices.popleft())
            try:
                t, frame = self._queue.get(timeout=1.0)
            except queue.Empty:
                if self._done:
                    return
                if not buffering and not self._reconnecting and time.monotonic() - last > self.BUFFERING_AFTER:
                    buffering = True
                    self._say("buffering", f"BUFFERING - no video from the stream for {self.BUFFERING_AFTER:.0f} s (slow "
                                           "connection, an ad break or the stream paused). Waiting.")
                continue
            if buffering:
                buffering = False
                self._say("live", "video is coming in again - counting continues.")
            last = time.monotonic()
            self.frames_processed += 1
            self._last_t = t
            yield t, frame

    def request_stop(self):
        self._stop.set()
        self._kill()

    def close(self, wait=True):
        self.request_stop()
        if wait:
            for proc in self._procs:
                try:
                    proc.wait(timeout=3)
                except (subprocess.TimeoutExpired, OSError):
                    pass

    def elapsed(self):
        return self._last_t


def make_source(kind, fps, device=None, monitor=1, video=None, start=0.0, duration=None, window=None, url=None,
                quality="720p"):
    """Build a LiveSource for one of the backends."""
    if kind in ("obs-camera", "device"):
        name = "OBS Virtual Camera" if kind == "obs-camera" else device
        if not name:
            raise ValueError("source 'device' needs a device name: pick it in the app, or set [live] device in config.toml (diagnostics lists the names)")
        return LiveSource(f"{kind}: {name}", ["-fflags", "nobuffer", "-f", "dshow", "-rtbufsize", "64M", "-i", f"video={name}"], fps)
    if kind == "desktop":
        monitors = list_monitors()
        if not 1 <= monitor <= len(monitors):
            raise ValueError(f"monitor {monitor} not found; available: 1..{len(monitors)}")
        x, y, w, h = monitors[monitor - 1]
        return LiveSource(f"desktop: monitor {monitor} ({w}x{h} at {x},{y})",
                          ["-f", "gdigrab", "-draw_mouse", "0", "-framerate", "30", "-offset_x", str(x), "-offset_y", str(y),
                           "-video_size", f"{w}x{h}", "-i", "desktop"], fps)
    if kind == "window":
        if not window:
            raise ValueError("source 'window' needs a window title: pick the OBS projector in the app's Video source list, "
                             "or set [live] window in config.toml")
        return WindowSource(window, fps)
    if kind == "stream":
        if not url:
            raise ValueError("source 'stream' needs a URL: paste the Twitch or YouTube link in the app, or set [live] url "
                             "in config.toml")
        return StreamSource(url, fps, quality)
    if kind == "file":
        args = ["-re"] + (["-ss", f"{start:.3f}"] if start else []) + (["-t", f"{duration:.3f}"] if duration else []) + ["-i", str(video)]
        return LiveSource(f"file (real time): {video}", args, fps)
    raise ValueError(f"unknown source '{kind}'")
