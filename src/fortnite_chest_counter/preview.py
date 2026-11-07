"""
Live video preview for the desktop app.

The counting worker copies a small version (640x360) of the frame it is analysing into a named shared-memory block a few
times per second; the app reads it from there. PRESENTATION ONLY: it never changes what is analysed, and while the app's
preview is hidden (the default) the worker does not even copy - it reads one flag per frame and moves on.

Block layout (little endian):  seq u32 | width u32 | height u32 | wanted u32 | t f64 | RGB bytes (width * height * 3)
  seq     even = a complete picture, odd = being written (a reader that sees seq change while copying drops that copy)
  wanted  1 while the app shows the preview (written by the app, read by the worker)
Windows named shared memory (mmap tagname); the app creates the block and keeps it for its lifetime.
"""

import mmap
import struct
import time

import numpy as np

WIDTH, HEIGHT = 640, 360
_HEADER = struct.Struct("<IIIId")
_DATA = _HEADER.size
SIZE = _DATA + WIDTH * HEIGHT * 3
FPS = 5


def block_name(tag):
    return f"Local\\FortniteVisualChestCounter-preview-{tag}"


class PreviewWriter:
    """Worker side. `offer` is called once per analysed frame; it is cheap unless the app wants a picture now."""

    def __init__(self, name, fps=FPS):
        self.mm = mmap.mmap(-1, SIZE, tagname=name)
        self.interval = 1.0 / fps
        self.next = 0.0
        self.seq = struct.unpack_from("<I", self.mm, 0)[0] & ~1          # continue a previous run's numbering

    def wanted(self):
        return struct.unpack_from("<I", self.mm, 12)[0] == 1

    def offer(self, t, frame):
        now = time.monotonic()
        if now < self.next or not self.wanted():
            return False
        self.next = now + self.interval
        if frame.shape[0] < 2 * HEIGHT or frame.shape[1] < 2 * WIDTH:
            return False
        small = np.ascontiguousarray(frame[:2 * HEIGHT:2, :2 * WIDTH:2, :3], dtype=np.uint8)
        self.seq += 1                                                       # odd: writing
        struct.pack_into("<I", self.mm, 0, self.seq)
        self.mm[_DATA:SIZE] = small.tobytes()
        struct.pack_into("<II", self.mm, 4, WIDTH, HEIGHT)
        struct.pack_into("<d", self.mm, 16, float(t))
        self.seq += 1                                                       # even: complete
        struct.pack_into("<I", self.mm, 0, self.seq)
        return True

    def close(self):
        try:
            self.mm.close()
        except Exception:
            pass


class PreviewReader:
    """App side: owns the block, tells the worker whether to send pictures, reads the newest complete one."""

    def __init__(self, name):
        self.name = name
        self.mm = mmap.mmap(-1, SIZE, tagname=name)
        self.last = None

    def set_wanted(self, on):
        struct.pack_into("<I", self.mm, 12, 1 if on else 0)

    def read(self):
        """-> (t, width, height, RGB bytes) for a picture not returned before, else None."""
        seq, width, height, _, t = _HEADER.unpack_from(self.mm, 0)
        if seq == 0 or seq % 2 or seq == self.last or (width, height) != (WIDTH, HEIGHT):
            return None
        data = self.mm[_DATA:SIZE]
        if struct.unpack_from("<I", self.mm, 0)[0] != seq:                 # rewritten while copying: skip this one
            return None
        self.last = seq
        return t, width, height, data

    def close(self):
        try:
            self.set_wanted(False)
            self.mm.close()
        except Exception:
            pass
