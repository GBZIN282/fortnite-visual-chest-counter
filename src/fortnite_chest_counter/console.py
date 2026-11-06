"""
The live console window: colours and verbosity. PRESENTATION ONLY - nothing here changes what is counted, saved or logged
(the session log in logs/ stays plain JSON lines).

Colour meaning (the same everywhere):
    green    [CERTAIN] a chest counted as certain (it also adds to APPROX)
    yellow   [APPROX ] a chest counted in APPROX only
    red      [REJECT ] a candidate that was NOT counted
    white-on-red  ERROR   something went wrong (setup problem, device unavailable, ...)
    magenta  WARNING   worth knowing, counting continues
    cyan     [STATUS ] / info lines

Verbosity:
    minimal  counted chests, warnings, errors, start/stop
    normal   + rejected pop-ups and a status line every few seconds          (default)
    debug    + every candidate (also generic button prompts) with its full reason and event id

Colours use ANSI escape codes, enabled on Windows 10/11 consoles (Command Prompt and Windows Terminal) with
ENABLE_VIRTUAL_TERMINAL_PROCESSING. They are switched off automatically when the output is not a console (redirected
to a file, tests) or when NO_COLOR is set, so the plain text always stays readable.
"""

import os
import sys
import time

VERBOSITY = ("minimal", "normal", "debug")
_CODES = {"green": "92", "yellow": "93", "red": "91", "cyan": "96", "magenta": "95", "dim": "90", "bold": "1",
          "error": "97;41"}


def _enable_windows_ansi(stream):
    """Turn on ANSI escape processing for this console. -> True if colours will work."""
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)                                   # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(mode.value & 0x0004) or bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _why(ev):
    """A short, plain-language reason for the decision (the full reason stays in the log and debug mode)."""
    r = ev.get("reason", "")
    counted = ev.get("certain_counted") or ev.get("approx_counted")
    if "promoted to HIGH" in r:
        return "confirmed by compression check"
    if "adjusted to LOW" in r:
        return "shooting at the same moment" if ev.get("shooting_negative") else "weak evidence"
    if "adjusted to HIGH" in r:
        return "button prompt seen"
    if "chest-object prompt support" in r:
        return "chest seen near the button prompt"
    if "shooting ignored" in r:
        return "shooting ignored for this word"
    if ev.get("source") == "interaction_object":
        return "button prompt + chest, no pop-up" if counted else "button prompt without a chest"
    if not counted and ev.get("adjusted_tier") == "MEDIUM":
        return "too weak alone for this word"
    return ""


def _evidence(ev):
    """What was measured, worded so it is not mistaken for a probability."""
    if ev.get("popup_score") is not None:
        return f"match {ev['popup_score']:.2f} ({ev.get('adjusted_tier', '?')})"
    return f"prompt {ev.get('interaction_score', 0):.2f}"


class Console:
    def __init__(self):
        self.verbosity, self.colors = "normal", False

    def configure(self, verbosity="normal", colors=True, stream=None):
        self.verbosity = verbosity if verbosity in VERBOSITY else "normal"
        self.colors = bool(colors) and "NO_COLOR" not in os.environ and _enable_windows_ansi(stream or sys.stdout)

    # ---- low level
    def paint(self, text, style):
        return f"\x1b[{_CODES[style]}m{text}\x1b[0m" if self.colors and style else text

    def line(self, text="", style=None):
        try:
            print(self.paint(text, style) if text else text, flush=True)
        except (OSError, ValueError):
            pass                                        # console already gone (window closed): never disturb counting

    # ---- message types
    def info(self, text):
        self.line(text, "cyan")

    def warn(self, text):
        self.line(f"{self.paint('WARNING', 'magenta')}: {text}" if self.colors else f"WARNING: {text}")

    def error(self, text):
        first, _, rest = str(text).partition("\n")
        self.line(f"{self.paint(' ERROR ', 'error')} {self.paint(first, 'red')}" if self.colors else f"ERROR: {first}")
        if rest:
            self.line(rest)

    def status(self, text):
        if self.verbosity != "minimal":
            self.line(f"{time.strftime('%H:%M:%S')}  {self.paint('[STATUS ]', 'cyan')}  {text}")

    def event(self, ev, certain_text, approx_text):
        """One detection decision. `certain_text` / `approx_text` = the running totals, already formatted."""
        certain, approx = ev.get("certain_counted"), ev.get("approx_counted")
        if not (certain or approx):
            if self.verbosity == "minimal":
                return
            if self.verbosity == "normal" and ev.get("source") == "interaction_object":
                return                                  # generic button prompts (pickups, ammo...): debug only
        if certain:
            tag, verdict, style = "[CERTAIN]", "chest +1", "green"
        elif approx:
            tag, verdict, style = "[APPROX ]", "chest ~+1", "yellow"
        else:
            tag, verdict, style = "[REJECT ]", "not counted", "red"
        why = _why(ev)
        # kept under ~118 characters so it never wraps in a standard 120-column console window
        text = (f"{time.strftime('%H:%M:%S')}  {self.paint(f'{tag} {verdict:11s}', style)} "
                f"CERTAIN {certain_text:>4s} | APPROX {approx_text:>4s}  {_evidence(ev)}" + (f" - {why}" if why else ""))
        self.line(text)
        if self.verbosity == "debug":
            self.line(f"            {ev.get('event_id', '')} at {ev.get('stamp', '')} | {ev.get('source', '')} | "
                      f"latency {ev.get('latency_s', 0):.1f}s | {ev.get('reason', '')}", "dim")


CONSOLE = Console()
