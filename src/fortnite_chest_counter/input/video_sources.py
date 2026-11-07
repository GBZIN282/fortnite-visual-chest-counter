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
  file        a video file played in real time. For testing the live pipeline without a device.
"""

import re
import subprocess
import threading
import time

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


def make_source(kind, fps, device=None, monitor=1, video=None, start=0.0, duration=None):
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
    if kind == "file":
        args = ["-re"] + (["-ss", f"{start:.3f}"] if start else []) + (["-t", f"{duration:.3f}"] if duration else []) + ["-i", str(video)]
        return LiveSource(f"file (real time): {video}", args, fps)
    raise ValueError(f"unknown source '{kind}'")
