"""
The desktop app's link to the counting worker.

The app never counts chests itself. It starts the SAME command-line program the console version runs
(`python -m fortnite_chest_counter live --gui`), without a console window, and only observes it: one JSON message per line
on the worker's stdout, plain text on stderr. Stop = the line "stop" on the worker's stdin; if the app disappears, Windows
closes that pipe and the worker stops and saves by itself. So hiding panels, a busy or frozen window, or even a crash of
the app can never make the counter miss or lose a chest.

Reader threads put messages in a queue; the app drains it from its own (GUI) thread with a timer.
"""

import json
import os
import queue
import subprocess
import threading

from fortnite_chest_counter import paths

CREATE_NO_WINDOW = 0x08000000


class Worker:
    def __init__(self):
        self.messages = queue.Queue()
        self.process = None
        self.stderr_tail = []
        self.exit_code = None
        self._lock = threading.Lock()

    def running(self):
        return self.process is not None and self.exit_code is None

    def start(self, argv):
        """Start `python -m fortnite_chest_counter <argv>` (argv should include --gui)."""
        if self.running():
            raise RuntimeError("the worker is already running")
        cmd = [paths.worker_python(), "-m", "fortnite_chest_counter", *argv]
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.stderr_tail, self.exit_code = [], None
        self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        cwd=str(paths.APP_DIR), env=env,
                                        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        out = threading.Thread(target=self._read_stdout, args=(self.process,), daemon=True, name="worker-stdout")
        err = threading.Thread(target=self._read_stderr, args=(self.process,), daemon=True, name="worker-stderr")
        out.start()
        err.start()
        threading.Thread(target=self._wait, args=(self.process, out, err), daemon=True, name="worker-wait").start()

    def stop(self):
        """Ask for a normal stop (the worker finishes the current frame, saves, reports and exits)."""
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            process.stdin.write(b"stop\n")
            process.stdin.flush()
            process.stdin.close()
        except OSError:
            pass

    def kill(self):
        process = self.process
        if process is not None and process.poll() is None:
            process.kill()

    # ---- threads
    def _read_stdout(self, process):
        for raw in process.stdout:
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                continue
            try:
                message = json.loads(text)
                if not isinstance(message, dict) or "type" not in message:
                    raise ValueError
            except ValueError:
                message = {"type": "line", "text": text}            # e.g. the reassuring lines after a crash report
            self.messages.put(message)

    def _read_stderr(self, process):
        for raw in process.stderr:
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if text:
                self.stderr_tail = (self.stderr_tail + [text])[-30:]
                self.messages.put({"type": "stderr", "text": text})

    def _wait(self, process, out, err):
        code = process.wait()
        out.join(timeout=5)
        err.join(timeout=5)
        if process is self.process:
            self.exit_code = code
        self.messages.put({"type": "exit", "code": code})

    def drain(self, limit=500):
        """Messages received since the last call (GUI thread)."""
        items = []
        while len(items) < limit:
            try:
                items.append(self.messages.get_nowait())
            except queue.Empty:
                break
        return items


def run_command(argv, timeout=120):
    """Run a short command of the program (e.g. diagnostics) without a console window. -> (exit code, output text)."""
    result = subprocess.run([paths.worker_python(), "-m", "fortnite_chest_counter", *argv], capture_output=True,
                            cwd=str(paths.APP_DIR), timeout=timeout,
                            env=dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8"),
                            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    text = result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")
    return result.returncode, text
