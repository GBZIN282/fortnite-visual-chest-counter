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

    def __init__(self, seconds=(3,), fail=None, realtime=False, log_line=None):
        super().__init__("https://example.invalid/live", 15)
        self.plan, self.fail, self.connections, self.edges = list(seconds), fail, 0, []
        self.realtime, self.log_line = realtime, log_line

    def streamlink_command(self, live_edge):
        self.connections += 1
        self.edges.append(live_edge)
        if self.fail:
            return [sys.executable, "-c", f"import sys; sys.stderr.write('error: {self.fail}\\n'); sys.exit(1)"]
        seconds = self.plan.pop(0) if self.plan else 600
        ff = ["ffmpeg", "-hide_banner", "-loglevel", "error"] + (["-re"] if self.realtime else []) + [
              "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", str(seconds), "-c:v", "mpeg2video", "-q:v", "5",
              "-f", "mpegts", "-"]
        if not self.log_line:
            return ff
        return [sys.executable, "-c", "import subprocess, sys; sys.stderr.write(sys.argv[1] + '\\n'); sys.stderr.flush(); "
                                      "subprocess.run(sys.argv[2:])", self.log_line, *ff]


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


def test_reconnects_keep_the_stability_presets_distance_from_live():
    s = FakeStream(seconds=(1, 1, 600))
    try:
        s.open()
        take(s, 40)
    finally:
        s.close()
    assert s.connections >= 3 and set(s.edges) == {sources.STREAM_STABILITY["maximum"]["live_edge"]}
    cmd = sources.StreamSource("https://x.invalid", 15, stability="low_latency").streamlink_command(2)
    assert cmd[cmd.index("--ringbuffer-size") + 1] == "16M" and cmd[cmd.index("--hls-live-edge") + 1] == "2"


def test_video_streamlink_had_to_skip_is_reported():
    s = FakeStream(seconds=(600,), log_line="[stream.hls][warning] Skipped segments 10-12 after playlist reload.")
    with machine_mode() as buf:
        try:
            s.open()
            take(s, 30)
        finally:
            s.close()
    states = [json.loads(l).get("state") for l in buf.getvalue().splitlines() if l.startswith("{")]
    assert "incomplete" in states


def test_a_pc_that_cannot_keep_up_is_told_once():
    s = FakeStream(seconds=(600,), realtime=True)
    s.LAG_WARN_AFTER, s.LAG_OK_BELOW = 1.0, 0.5
    with machine_mode() as buf:
        try:
            s.open()
            take(s, 25, slow=0.15)                      # ~6.7 analysed per second for a 15 per second stream
        finally:
            s.close()
    states = [json.loads(l).get("state") for l in buf.getvalue().splitlines() if l.startswith("{")]
    assert states.count("lagging") == 1 and s.backlog_seconds() > 1.0


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
