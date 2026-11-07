"""
Time-remaining estimates for long jobs (Analyse a recording, Review captures). No Qt here, so it is unit-tested.

The estimate comes only from MEASURED throughput: video seconds processed per wall-clock second, smoothed with an
exponential moving average. Until enough has been measured (a few seconds and a few percent of the work) it returns
None and the app shows progress without a time - it never invents one.
"""

import time


class Eta:
    def __init__(self, min_elapsed=3.0, min_fraction=0.02, alpha=0.25, clock=time.monotonic):
        self.min_elapsed, self.min_fraction, self.alpha, self.clock = min_elapsed, min_fraction, alpha, clock
        self.start = self.last_t = None
        self.first_done = self.last_done = 0.0
        self.rate = None

    def update(self, done, total):
        """-> estimated seconds remaining, or None while unknown."""
        now = self.clock()
        if self.start is None:                     # the first report starts the clock (start-up time is not throughput)
            self.start, self.last_t, self.first_done, self.last_done = now, now, done, done
            return None
        dt = now - self.last_t
        if dt >= 0.5 and done > self.last_done:
            rate = (done - self.last_done) / dt
            self.rate = rate if self.rate is None else self.alpha * rate + (1 - self.alpha) * self.rate
            self.last_t, self.last_done = now, done
        if (self.rate is None or not total or now - self.start < self.min_elapsed
                or (done - self.first_done) / total < self.min_fraction):
            return None
        return max(total - done, 0.0) / self.rate


def describe(seconds):
    """'about 2 min 10 s left' style text for an estimate (None -> '')."""
    if seconds is None:
        return ""
    if seconds < 10:
        return "less than 10 s left"
    seconds = int(round(seconds / 5.0) * 5) if seconds < 120 else int(round(seconds / 10.0) * 10)
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"about {hours} h {minutes} min left"
    if minutes:
        return f"about {minutes} min {rest} s left" if rest and minutes < 10 else f"about {minutes} min left"
    return f"about {rest} s left"


def clock_text(seconds):
    """Video position as m:ss or h:mm:ss."""
    seconds = int(max(seconds, 0))
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"
