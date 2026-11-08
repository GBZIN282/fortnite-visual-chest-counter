"""
Livestream URL input (v0.2.1): StreamSource with a stand-in for Streamlink (FFmpeg writing an MPEG-TS test picture to
stdout), so no network is needed. Every picture arrives, in order, in stream time; a failure before the first picture is
reported; a drop is reconnected with the time line moved on; Stop leaves no process behind.
Run:   python tests/test_stream.py     (or pytest)
"""
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "src"))   # run without installing

import contextlib
import io
import json
import time

from fortnite_chest_counter.console import CONSOLE
from fortnite_chest_counter.input import video_sources as sources


class FakeStream(sources.StreamSource):
    """Streamlink replaced by FFmpeg: `seconds` of 30 fps test video per connection, as fast as it can (a burst)."""
    RECONNECT_DELAYS = (0.2,)

    def __init__(self, seconds=(3,), fail=None):
        super().__init__("https://example.invalid/live", 15)
        self.plan, self.fail, self.connections = list(seconds), fail, 0

    def streamlink_command(self, live_edge):
        self.connections += 1
        if self.fail:
            return [sys.executable, "-c", f"import sys; sys.stderr.write('error: {self.fail}\\n'); sys.exit(1)"]
        seconds = self.plan.pop(0) if self.plan else 600
        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                "-t", str(seconds), "-c:v", "mpeg2video", "-q:v", "5", "-f", "mpegts", "-"]


@contextlib.contextmanager
def machine_mode():
    buf = io.StringIO()
    CONSOLE.machine = True
    try:
        with contextlib.redirect_stdout(buf):
            yield buf
    finally:
        CONSOLE.machine = False


def take(source, n, slow=0.0, timeout=30):
    out, deadline = [], time.monotonic() + timeout
    for t, frame in source.frames():
        out.append(t)
        assert frame.shape == (sources.HEIGHT, sources.WIDTH, 3)
        if slow:
            time.sleep(slow)                                # a detector slower than the burst
        if len(out) >= n or time.monotonic() > deadline:
            break
    return out


def test_every_picture_arrives_in_order_in_stream_time_even_with_a_slow_detector():
    s = FakeStream(seconds=(3, 600))
    try:
        s.open()
        times = take(s, 45, slow=0.03)
    finally:
        s.close()
    assert len(times) == 45 and s.frames_dropped == 0
    assert all(abs((b - a) - 1 / 15) < 1e-9 for a, b in zip(times, times[1:]))   # stream time, not arrival time
    assert s.info["input_resolution"] == (640, 360)


def test_a_stream_that_cannot_be_opened_is_reported_not_retried():
    s = FakeStream(fail="No playable streams found on this URL: https://example.invalid/live")
    try:
        s.open()
    except RuntimeError as error:
        assert "No playable streams found" in str(error)
    else:
        raise AssertionError("no error")
    assert s.connections == 1


def test_a_dropped_stream_reconnects_and_moves_the_time_line_on():
    s = FakeStream(seconds=(1, 600))
    with machine_mode() as buf:
        try:
            s.open()
            times = take(s, 30)
        finally:
            s.close()
    texts = [json.loads(l).get("text", "") for l in buf.getvalue().splitlines() if l.startswith("{")]
    assert s.connections >= 2
    assert any("Reconnecting in" in t for t in texts) and any("RECONNECTED" in t for t in texts) and any("missing from the count" in t for t in texts)
    assert all(b > a for a, b in zip(times, times[1:]))                         # never back in time
    jumps = [b - a for a, b in zip(times, times[1:]) if b - a > 1 / 15 + 1e-9]
    assert jumps and jumps[0] >= 0.2                                            # the missed part is skipped, not replayed


def test_stop_ends_both_processes():
    s = FakeStream(seconds=(600,))
    s.open()
    take(s, 5)
    procs = s._procs
    s.close()
    assert all(p.poll() is not None for p in procs)


def test_make_source_needs_a_url():
    try:
        sources.make_source("stream", 15, url="")
    except ValueError as error:
        assert "needs a URL" in str(error)
    else:
        raise AssertionError("no error")
    assert sources.make_source("stream", 15, url="https://www.twitch.tv/x").quality == "720p60,720p,best"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok    {t.__name__}")
        except Exception as error:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL  {t.__name__}: {error!r}")
    print(f"{len(tests) - failed}/{len(tests)} stream checks passed")
    raise SystemExit(1 if failed else 0)
