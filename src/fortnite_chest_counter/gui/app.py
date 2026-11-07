"""
Fortnite Visual Chest Counter - the desktop app.

    runtime\\python\\pythonw.exe -m fortnite_chest_counter.gui      (what "Fortnite Visual Chest Counter.exe" starts)

The window is a remote control and a viewer. Counting runs in a separate worker process - the same `live` command the
console version uses - and the window only observes it (see worker.py). Closing the activity panel, hiding the preview,
minimising or even a crash of the window never interrupts counting; every setting it changes goes through the same
config.toml / state file as the command line, so the two always agree.
"""

import ctypes
import json
import os
import sys
import threading
import time
import traceback
import uuid
from collections import deque
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImage, QPalette, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
                               QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from fortnite_chest_counter import counter as C
from fortnite_chest_counter import paths, settings
from fortnite_chest_counter.gui import theme
from fortnite_chest_counter.gui.worker import Worker, run_command
from fortnite_chest_counter.preview import PreviewReader, block_name
from fortnite_chest_counter.version import APP_NAME, RELEASE_CHANNEL, TAGLINE, __version__

ASSETS = Path(__file__).resolve().parent / "assets"
APP_ID = "GabrielGzS.FortniteVisualChestCounter"
REPO_URL = "https://github.com/GabrielGzS/fortnite-visual-chest-counter"
LOG_LIMIT = 3000
fmt = settings.format_count


# ==================================================================
# small helpers
# ==================================================================

def app_icon():
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addFile(str(ASSETS / f"icon_{size}.png"), QSize(size, size))
    return icon


def open_path(path):
    path = Path(path)
    if path.is_dir() or path.is_file():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))


def config_file():
    return paths.APP_DIR / settings.DEFAULT_CONFIG_PATH


def load_cfg():
    cfg, _, warnings = settings.load_config(str(config_file()) if config_file().exists() else None)
    return cfg, warnings


def read_counts(state_path):
    """(certain, approx) from the counter file, or None. Read-only: unlike load_state it never moves a file."""
    try:
        raw = json.loads(Path(state_path).read_text(encoding="utf-8"))
        certain, approx = raw["certain"], raw["approximate"]
        if isinstance(certain, int) and isinstance(approx, int):
            return certain, max(approx, certain)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, name=None, tip=None, on_click=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    if tip:
        widget.setToolTip(tip)
    if on_click:
        widget.clicked.connect(on_click)
    widget.setCursor(Qt.PointingHandCursor)
    return widget


def restyle(widget, name):
    """Give a widget another style name (e.g. primary -> danger). Qt only re-reads the style sheet after a re-polish."""
    widget.setObjectName(name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def card(title=None, hint=None):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    if title:
        layout.addWidget(label(title, "cardTitle"))
    if hint:
        layout.addWidget(label(hint, "hint", wrap=True))
    return frame, layout


def page_layout(widget, title, subtitle):
    """A scrollable page with a title. -> the content layout."""
    widget.setObjectName("page")
    outer = QVBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    inner = QWidget()
    inner.setObjectName("page")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(30, 24, 30, 24)
    layout.setSpacing(16)
    layout.addWidget(label(title, "pageTitle"))
    if subtitle:
        layout.addWidget(label(subtitle, "pageSub", wrap=True))
    scroll.setWidget(inner)
    outer.addWidget(scroll)
    return layout


def hline():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.BORDER};")
    return line


def ask(parent, title, text, yes="Yes", no="Cancel", danger=False):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    ok = box.addButton(yes, QMessageBox.AcceptRole)
    box.addButton(no, QMessageBox.RejectRole)
    box.setDefaultButton(ok)
    box.exec()
    return box.clickedButton() is ok


def show_error(parent, text):
    QMessageBox.warning(parent, APP_NAME, text)


# ==================================================================
# activity console formatting
# ==================================================================

VERDICT = {"certain": ("CHEST +1", theme.CERTAIN), "approx": ("CHEST ~+1", theme.APPROX),
           "rejected": ("not counted", theme.REJECT)}


def _span(text, color, bold=False):
    weight = "font-weight:600;" if bold else ""
    return f'<span style="color:{color};{weight}">{escape(str(text))}</span>'


def _pad(text, width):
    return escape(text) + "&nbsp;" * max(width - len(text), 0)


def log_entries(message):
    """-> [(debug_only, html)] for one worker message."""
    kind = message.get("type")
    clock = message.get("clock") or time.strftime("%H:%M:%S")
    stamp = _span(clock, theme.DIM) + "&nbsp;&nbsp;"
    if kind == "event":
        text, color = VERDICT.get(message.get("verdict"), ("?", theme.MUTED))
        if message.get("generic"):
            text, color = "prompt only", theme.DIM
        why = f" - {message['why']}" if message.get("why") else ""
        totals = ""
        if message.get("certain_text") is not None:
            totals = "&nbsp;" * 3 + _span(f"CERTAIN {message['certain_text']} | APPROX {message['approx_text']}", theme.DIM)
        main = (stamp + f'<span style="color:{color};font-weight:600">{_pad(text, 12)}</span>'
                + escape(f"{message.get('evidence', '')}{why}") + totals)
        detail = "&nbsp;" * 10 + _span(f"{message.get('event_id', '')} at {message.get('stamp', '')} | {message.get('source', '')}"
                       f" | latency {message.get('latency_s') or 0:.1f}s | {message.get('reason', '')}", theme.DIM)
        return [(bool(message.get("generic")), main), (True, detail)]
    if kind == "status":
        return [(True, stamp + _span(message.get("text", ""), theme.DIM))]
    if kind in ("info", "warn", "error", "line", "stderr"):
        text = str(message.get("text", "")).strip("\n")
        if not text:
            return []
        color = theme.LOG_COLORS.get(kind, theme.MUTED)
        prefix = {"warn": "Warning: ", "error": "Error: "}.get(kind, "")
        debug_only = kind == "stderr"
        lines = text.split("\n")
        out = [(debug_only, stamp + _span(prefix + lines[0], color, bold=kind == "error"))]
        out += [(debug_only, "&nbsp;" * 10 + _span(line, color)) for line in lines[1:] if line.strip()]
        return out
    return []


# ==================================================================
# widgets
# ==================================================================

class CountCard(QFrame):
    def __init__(self, title, subtitle, color):
        super().__init__()
        self.setObjectName("countCard")
        self.color = color
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 18, 0)
        layout.setSpacing(16)
        bar = QFrame()
        bar.setFixedWidth(5)
        bar.setStyleSheet(f"background: {color}; border-top-left-radius: 12px; border-bottom-left-radius: 12px;")
        layout.addWidget(bar)
        box = QVBoxLayout()
        box.setContentsMargins(0, 14, 0, 14)
        box.setSpacing(0)
        box.addWidget(label(title, "countLabel"))
        self.value = label("0", "countValue")
        self.value.setStyleSheet(f"color: {color};")
        box.addWidget(self.value)
        box.addWidget(label(subtitle, "countSub", wrap=True))
        layout.addLayout(box, 1)
        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(lambda: self.setStyleSheet(""))

    def set_value(self, value, flash=False):
        text = fmt(value)
        if text != self.value.text() and flash:
            self.setStyleSheet(f"#countCard {{ border: 1px solid {self.color}; background: {theme.rgba(self.color, 0.08)}; }}")
            self._flash.start(900)
        self.value.setText(text)


class PreviewPanel(QFrame):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.view = QLabel("Start counting to see the video here")
        self.view.setObjectName("previewBox")
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(320, 180)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.view, 1)
        self.caption = label("Preview: what the counter analyses (a few pictures per second).", "hint", wrap=True)
        layout.addWidget(self.caption)
        self.image = None

    def show_frame(self, width, height, data):
        self.image = QImage(data, width, height, 3 * width, QImage.Format_RGB888).copy()
        self._render()

    def clear(self, text="Start counting to see the video here"):
        self.image = None
        self.view.setPixmap(QPixmap())
        self.view.setText(text)

    def _render(self):
        if self.image is None:
            return
        size = self.view.size() - QSize(4, 4)
        self.view.setPixmap(QPixmap.fromImage(self.image).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()


# ==================================================================
# dialogs
# ==================================================================

class CountsDialog(QDialog):
    """Set the counter (also: start from the chests already opened)."""

    def __init__(self, parent, certain, approx):
        super().__init__(parent)
        self.setWindowTitle("Edit counts")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(label("Set the counter", "cardTitle"))
        layout.addWidget(label("Use this to start from the chests you already opened before using the counter, or to "
                               "correct a mistake. New chests are added on top.", "hint", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.approx = QSpinBox()
        self.certain = QSpinBox()
        for spin, value in ((self.approx, approx), (self.certain, certain)):
            spin.setRange(0, C.MAX_STARTING_COUNT)
            spin.setGroupSeparatorShown(True)
            spin.setValue(value)
            spin.setMinimumWidth(140)
        grid.addWidget(label("Chests opened (APPROX, the total)"), 0, 0)
        grid.addWidget(self.approx, 0, 1)
        grid.addWidget(label("Confirmed chests (CERTAIN)"), 1, 0)
        grid.addWidget(self.certain, 1, 1)
        layout.addLayout(grid)
        layout.addWidget(label("CERTAIN is part of APPROX, so it cannot be higher. Chests opened before the counter ran "
                               "were not seen by it: leave CERTAIN at 0 for those.", "hint", wrap=True))
        self.problem = label("", "hint")
        self.problem.setStyleSheet(f"color: {theme.REJECT};")
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.approx.valueChanged.connect(self._check)
        self.certain.valueChanged.connect(self._check)

    def _check(self):
        bad = self.certain.value() > self.approx.value()
        self.problem.setText("CERTAIN cannot be higher than APPROX." if bad else "")
        return not bad

    def _accept(self):
        if self._check():
            self.accept()


class VideoDialog(QDialog):
    """Count the chests in a recorded gameplay video (the `video` command). Never touches the live counter."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Analyse a recording")
        self.resize(640, 520)
        self.worker = Worker()
        self.duration = None
        self.result_dir = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(label("Count the chests in a recorded gameplay video", "cardTitle"))
        layout.addWidget(label("Runs faster than real time. Your live counter and OBS overlay are not changed; the result "
                               "files go to the video_output folder.", "hint", wrap=True))
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("Choose a video file (.mp4, .mkv, .mov ...)")
        row.addWidget(self.path, 1)
        row.addWidget(button("Browse...", on_click=self._browse))
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.state = label("", "hint")
        layout.addWidget(self.state)
        counts = QHBoxLayout()
        self.certain = CountCard("CERTAIN", "confirmed", theme.CERTAIN)
        self.approx = CountCard("APPROX", "estimated total", theme.APPROX)
        counts.addWidget(self.certain)
        counts.addWidget(self.approx)
        layout.addLayout(counts)
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(LOG_LIMIT)
        layout.addWidget(self.log, 1)
        bottom = QHBoxLayout()
        self.open_results = button("Open results folder", on_click=lambda: open_path(self.result_dir))
        self.open_results.setEnabled(False)
        bottom.addWidget(self.open_results)
        bottom.addStretch(1)
        self.go = button("Start", "primary", on_click=self._toggle)
        self.go.setEnabled(False)
        bottom.addWidget(self.go)
        bottom.addWidget(button("Close", on_click=self.close))
        layout.addLayout(bottom)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._pump)
        self.timer.start(60)

    def _browse(self):
        start = str(Path.home() / "Videos")
        name, _ = QFileDialog.getOpenFileName(self, "Choose a gameplay video", start,
                                              "Videos (*.mp4 *.mkv *.mov *.avi *.flv *.ts *.webm);;All files (*)")
        if name:
            self.path.setText(name)
            self.go.setEnabled(True)

    def _toggle(self):
        if self.worker.running():
            self.worker.stop()
            self.go.setEnabled(False)
            self.state.setText("Stopping...")
            return
        self.log.clear()
        self.certain.set_value(0)
        self.approx.set_value(0)
        self.progress.setValue(0)
        self.open_results.setEnabled(False)
        try:
            self.worker.start(["video", self.path.text(), "--gui"])
        except OSError as error:
            show_error(self, f"The analysis could not start ({error}).")
            return
        self.go.setText("Stop")
        restyle(self.go, "danger")
        self.state.setText("Starting...")

    def _pump(self):
        for message in self.worker.drain():
            kind = message.get("type")
            if kind == "video_start":
                self.duration = message.get("duration")
                self.state.setText(f"Analysing {message.get('name', '')} ...")
            elif kind == "progress":
                t = message.get("t", 0)
                if self.duration:
                    self.progress.setValue(int(1000 * min(t / self.duration, 1.0)))
                    self.state.setText(f"{C.mmss(t)[:-3]} of {C.mmss(self.duration)[:-3]} analysed")
                else:
                    self.progress.setRange(0, 0)
                self.certain.set_value(message.get("certain", 0))
                self.approx.set_value(message.get("approx", 0))
            elif kind == "event":
                if message.get("verdict") in ("certain", "approx"):
                    for debug_only, html in log_entries(message):
                        if not debug_only:
                            self.log.appendHtml(html)
                if message.get("certain") is not None:
                    self.certain.set_value(message["certain"], flash=True)
                    self.approx.set_value(message["approx"], flash=True)
            elif kind == "finished":
                self.progress.setRange(0, 1000)
                self.progress.setValue(1000 if not message.get("stopped_early") else self.progress.value())
                self.certain.set_value(message["certain"])
                self.approx.set_value(message["approx"])
                self.result_dir = message.get("obs_dir")
                self.open_results.setEnabled(bool(self.result_dir))
                early = " (stopped early: only the part already analysed is counted)" if message.get("stopped_early") else ""
                self.state.setText(f"Finished: {message.get('analysed', '')[:-3]} of video in {message.get('minutes', 0)} min{early}. "
                                   "APPROX is the estimated total and already includes CERTAIN.")
            elif kind in ("error", "warn"):
                for _, html in log_entries(message):
                    self.log.appendHtml(html)
                if kind == "error":
                    self.state.setText("Could not analyse this file - see the message below.")
            elif kind == "exit":
                self.go.setText("Start again")
                restyle(self.go, "primary")
                self.go.setEnabled(True)
                self.progress.setRange(0, 1000)

    def closeEvent(self, event):
        if self.worker.running():
            if not ask(self, "Stop the analysis?", "The video is still being analysed. Stop and close?", "Stop and close"):
                event.ignore()
                return
            self.worker.stop()
            deadline = time.monotonic() + 5
            while self.worker.running() and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.05)
            self.worker.kill()
        self.timer.stop()
        super().closeEvent(event)


# ==================================================================
# pages
# ==================================================================

class Dashboard(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = page_layout(self, "Dashboard", "Counts the chests in your gameplay video and writes the numbers to a "
                                                "text file that OBS shows on stream.")
        header = layout.itemAt(0).widget()
        layout.removeWidget(header)
        top = QHBoxLayout()
        top.addWidget(header)
        top.addStretch(1)
        self.pill = label("", "pill")
        top.addWidget(self.pill, 0, Qt.AlignVCenter)
        layout.insertLayout(0, top)

        # error banner
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(14, 10, 10, 10)
        self.banner_text = label("", "bannerText", wrap=True)
        self.banner_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        banner_layout.addWidget(self.banner_text, 1)
        banner_layout.addWidget(button("Dismiss", on_click=self.banner.hide), 0, Qt.AlignTop)
        self.banner.hide()
        layout.addWidget(self.banner)

        # the two numbers
        counts = QHBoxLayout()
        counts.setSpacing(14)
        self.certain = CountCard("CERTAIN", "Chests confirmed by strong evidence", theme.CERTAIN)
        self.approx = CountCard("APPROX", "Estimated total - already includes CERTAIN", theme.APPROX)
        counts.addWidget(self.certain, 1)
        counts.addWidget(self.approx, 1)
        actions = QVBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(button("Edit counts...", tip="Start from the chests you already opened, or correct the counter",
                                 on_click=win.edit_counts))
        actions.addWidget(button("Reset...", tip="Set both counts to 0", on_click=win.reset_counts))
        actions.addStretch(1)
        counts.addLayout(actions)
        layout.addLayout(counts)
        viewers = QHBoxLayout()
        viewers.addWidget(label("Viewers see:", "hint"), 0, Qt.AlignTop)
        self.viewers = label("", "hint", wrap=True)
        self.viewers.setStyleSheet(f"color: {theme.TEXT};")
        viewers.addWidget(self.viewers, 1)
        viewers.addWidget(button("Change what viewers see", "link", on_click=lambda: win.go_to(1)))
        layout.addLayout(viewers)

        # source + start
        box, box_layout = card()
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(label("Video source"))
        self.source = QComboBox()
        self.source.setMinimumWidth(220)
        self.source.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.source.setMinimumContentsLength(24)
        self.source.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(self.source, 1)
        self.refresh = button("Refresh", tip="Look for video devices and screens again", on_click=win.refresh_sources)
        row.addWidget(self.refresh)
        self.start = button("Start counting", "primary", on_click=win.toggle_counting)
        self.start.setMinimumWidth(160)
        row.addWidget(self.start)
        box_layout.addLayout(row)
        self.source_hint = label("", "hint", wrap=True)
        box_layout.addWidget(self.source_hint)
        box_layout.addWidget(hline())
        row = QHBoxLayout()
        self.metrics = label("Not counting.", "metrics", wrap=True)
        row.addWidget(self.metrics, 1)
        self.analyse = button("Analyse a recording...", tip="Count the chests in a video file (does not change your counter)",
                              on_click=win.analyse_video)
        row.addWidget(self.analyse)
        box_layout.addLayout(row)
        layout.addWidget(box)

        # optional panels
        row = QHBoxLayout()
        self.show_log = button("Activity", "toggle", tip="What the counter sees and decides, live")
        self.show_log.setCheckable(True)
        self.show_preview = button("Live preview", "toggle", tip="The video the counter is analysing")
        self.show_preview.setCheckable(True)
        row.addWidget(self.show_log)
        row.addWidget(self.show_preview)
        row.addStretch(1)
        self.detail = QComboBox()
        self.detail.addItem("Normal detail", "normal")
        self.detail.addItem("Debug detail", "debug")
        self.detail.setToolTip("Debug adds every candidate, the full reason for each decision and status lines")
        row.addWidget(self.detail)
        self.clear = button("Clear", on_click=win.clear_log)
        row.addWidget(self.clear)
        self.open_logs = button("Logs folder", tip="Session logs (send these when reporting a problem)",
                                on_click=win.open_logs)
        row.addWidget(self.open_logs)
        layout.addLayout(row)

        self.split = QSplitter(Qt.Horizontal)
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(LOG_LIMIT)
        self.log.setPlaceholderText("Chests appear here as they are counted: green = certain, yellow = estimated only, "
                                    "red = looked like a chest but was not counted.")
        self.log.setMinimumHeight(220)
        self.preview = PreviewPanel()
        self.split.addWidget(self.log)
        self.split.addWidget(self.preview)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        layout.addWidget(self.split, 1)

        self.show_log.toggled.connect(self._panels)
        self.show_preview.toggled.connect(self._panels)
        self.detail.currentIndexChanged.connect(lambda _: win.render_log())

    def _panels(self):
        self.log.setVisible(self.show_log.isChecked())
        self.preview.setVisible(self.show_preview.isChecked())
        for widget in (self.detail, self.clear):
            widget.setVisible(self.show_log.isChecked())
        self.split.setVisible(self.show_log.isChecked() or self.show_preview.isChecked())
        self.win.preview_visibility_changed()

    def set_pill(self, text, color):
        self.pill.setText(f"●  {text}")
        self.pill.setStyleSheet(theme.pill_style(color))

    def show_banner(self, text):
        self.banner_text.setText(text)
        self.banner.show()


class OverlayPage(QWidget):
    """Configure Counter.bat, as a page: what OBS shows (always the same file) and its wording."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = page_layout(self, "Overlay", "What your viewers see. The counter writes ONE text file; OBS shows it with a "
                                              "Text source. Fonts, colours and size are set in OBS.")
        box, box_layout = card("What OBS shows")
        self.modes = QButtonGroup(self)
        self.mode_buttons = {}
        for i, mode in enumerate(("stacked", "inline", "approx", "certain")):
            radio = QRadioButton()
            self.modes.addButton(radio, i)
            self.mode_buttons[mode] = radio
            box_layout.addWidget(radio)
            radio.toggled.connect(self._changed)
        layout.addWidget(box)

        box, box_layout = card("Wording", "Put # where the number goes, e.g.  Chests opened: #   or   Chest Hunt: #/500")
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.certain_label = label("Confirmed chests (CERTAIN)")
        self.certain_text = QLineEdit()
        self.approx_label = label("Estimated total (APPROX)")
        self.approx_text = QLineEdit()
        self.line_label = label("One line")
        self.line_text = QLineEdit()
        self.line_text.setToolTip("#C = confirmed number, #A = estimated total, e.g.  #C confirmed - #A total")
        for row, (lab, edit) in enumerate(((self.certain_label, self.certain_text), (self.approx_label, self.approx_text),
                                           (self.line_label, self.line_text))):
            form.addWidget(lab, row, 0)
            form.addWidget(edit, row, 1)
            edit.textChanged.connect(self._changed)
        form.setColumnStretch(1, 1)
        box_layout.addLayout(form)
        self.line_hint = label("For one line: #C = confirmed number, #A = estimated total.", "hint")
        box_layout.addWidget(self.line_hint)
        self.thousands = QCheckBox("Thousands separator (1,234 instead of 1234)")
        self.thousands.toggled.connect(self._changed)
        box_layout.addWidget(self.thousands)
        row = QHBoxLayout()
        row.addWidget(button("Original wording", "link", on_click=self._defaults))
        row.addStretch(1)
        box_layout.addLayout(row)
        layout.addWidget(box)

        box, box_layout = card("Preview", "Exactly what the text file contains (shown on black, like a stream overlay).")
        self.preview = label("", "overlayBox")
        self.preview.setTextFormat(Qt.PlainText)
        box_layout.addWidget(self.preview)
        layout.addWidget(box)

        box, box_layout = card("OBS setup", 'In OBS: add a "Text (GDI+)" source, tick "Read from file" and choose this file. '
                                            "It never changes, whatever you pick above.")
        row = QHBoxLayout()
        self.obs_path = QLineEdit()
        self.obs_path.setReadOnly(True)
        row.addWidget(self.obs_path, 1)
        row.addWidget(button("Copy path", on_click=self._copy_path))
        row.addWidget(button("Open folder", on_click=lambda: open_path(Path(self.obs_path.text()).parent)))
        box_layout.addLayout(row)
        layout.addWidget(box)

        row = QHBoxLayout()
        self.saved = label("", "hint")
        row.addWidget(self.saved, 1)
        row.addWidget(button("Undo changes", on_click=self.load))
        row.addWidget(button("Apply", "primary", on_click=self.apply))
        layout.addLayout(row)
        layout.addStretch(1)
        self._loading = False

    def load(self):
        self._loading = True
        cfg, _ = load_cfg()
        self.display = cfg["display"]
        self.obs_path.setText(str((paths.APP_DIR / cfg["state"]["obs_dir"] / "chest_counter.txt").resolve()))
        self.mode_buttons[C.display_mode(self.display)].setChecked(True)
        self.certain_text.setText(C.hash_from_text(self.display["certain_text"]))
        self.approx_text.setText(C.hash_from_text(self.display["approx_text"]))
        self.line_text.setText(C.markers_from_line(self.display["combined_status_format"]))
        self.thousands.setChecked(self.display["use_thousands_separator"])
        self._loading = False
        self.saved.setText("")
        self._changed()

    def _mode(self):
        return next(m for m, b in self.mode_buttons.items() if b.isChecked())

    def changes(self):
        mode = self._mode()
        texts = {"use_thousands_separator": self.thousands.isChecked()}
        if mode == "inline":
            if self.line_text.text().strip():
                texts["combined_status_format"] = C.line_from_markers(self.line_text.text())
        else:
            if mode in ("certain", "stacked") and self.certain_text.text().strip():
                texts["certain_text"] = C.text_from_hash(self.certain_text.text())
            if mode in ("approx", "stacked") and self.approx_text.text().strip():
                texts["approx_text"] = C.text_from_hash(self.approx_text.text())
        return {**C.MODE_SETTINGS[mode], **texts}

    def _state(self):
        certain, approx = self.win.counts
        return {"certain": certain, "approximate": approx}

    def _changed(self):
        if self._loading:
            return
        mode = self._mode()
        self.certain_label.setVisible(mode in ("certain", "stacked"))
        self.certain_text.setVisible(mode in ("certain", "stacked"))
        self.approx_label.setVisible(mode in ("approx", "stacked"))
        self.approx_text.setVisible(mode in ("approx", "stacked"))
        for widget in (self.line_label, self.line_text, self.line_hint):
            widget.setVisible(mode == "inline")
        preview = {**self.display, **self.changes()}
        self.preview.setText(C.overlay_text(preview, self._state()))
        state = self._state()
        for m, radio in self.mode_buttons.items():
            example = C.overlay_text({**self.display, **C.MODE_SETTINGS[m]}, state).replace("\n", "  /  ")
            radio.setText(f"{C.MODE_DESCRIPTIONS[m][0].upper()}{C.MODE_DESCRIPTIONS[m][1:]}      e.g.  {example}")
        pending = any(self.display.get(k) != v for k, v in self.changes().items())
        self.saved.setText("Not applied yet." if pending else "")

    def _defaults(self):
        d = settings.DEFAULTS["display"]
        self.certain_text.setText(C.hash_from_text(d["certain_text"]))
        self.approx_text.setText(C.hash_from_text(d["approx_text"]))
        self.line_text.setText(C.markers_from_line(d["combined_status_format"]))

    def _copy_path(self):
        QApplication.clipboard().setText(self.obs_path.text())
        self.saved.setText("Path copied - paste it into the OBS Text source.")

    def apply(self):
        changes = self.changes()
        try:
            C.update_config_file(config_file(), "display", changes)
        except (C.UserError, OSError) as error:
            show_error(self, str(error))
            return
        if not self.win.worker.running():
            self.win.write_obs_files()
        self.load()
        self.saved.setText("Applied. " + ("The counter updates the OBS text within a second."
                                          if self.win.worker.running() else "The OBS text file was updated."))
        self.win.refresh_viewers()


class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = page_layout(self, "Settings", "Changes are saved in config.toml next to the app and are used the next time "
                                               "you press Start counting.")
        box, box_layout = card("Fortnite language", "Which word the counter reads in the chest pop-up. Ticking only your "
                                                    "language gives slightly fewer false alarms.")
        self.lang_en = QCheckBox("English  (CHEST)")
        self.lang_pt = QCheckBox("Portuguese  (BAÚ)")
        box_layout.addWidget(self.lang_en)
        box_layout.addWidget(self.lang_pt)
        layout.addWidget(box)

        box, box_layout = card("Session logs", "Logs are small text files in the logs folder. They are what you send when "
                                               "reporting a problem.")
        self.logging = QCheckBox("Keep a log of every counting session")
        self.snapshots = QCheckBox("Also save a small picture of every chest pop-up (to report missed or wrong chests)")
        box_layout.addWidget(self.logging)
        box_layout.addWidget(self.snapshots)
        self.logging.toggled.connect(self.snapshots.setEnabled)
        layout.addWidget(box)

        box, box_layout = card("Advanced", "Everything else (detector cadence, which evidence counts) is in config.toml. "
                                           "Edit it only if you know why; a typo shows a warning and uses the default.")
        row = QHBoxLayout()
        row.addWidget(button("Open config.toml", on_click=self._open_config))
        row.addWidget(button("Open program folder", on_click=lambda: open_path(paths.APP_DIR)))
        row.addStretch(1)
        box_layout.addLayout(row)
        layout.addWidget(box)

        row = QHBoxLayout()
        self.saved = label("", "hint")
        row.addWidget(self.saved, 1)
        row.addWidget(button("Save", "primary", on_click=self.save))
        layout.addLayout(row)
        layout.addStretch(1)

    def load(self):
        cfg, _ = load_cfg()
        langs = cfg["detector"]["languages"]
        self.lang_en.setChecked("en" in langs)
        self.lang_pt.setChecked("pt" in langs)
        self.logging.setChecked(cfg["logging"]["enabled"])
        self.snapshots.setChecked(cfg["logging"]["save_snapshots"])
        self.snapshots.setEnabled(cfg["logging"]["enabled"])
        self.saved.setText("")

    def save(self):
        langs = [code for code, box in (("en", self.lang_en), ("pt", self.lang_pt)) if box.isChecked()]
        if not langs:
            show_error(self, "Tick at least one language.")
            return
        try:
            C.update_config_file(config_file(), "detector", {"languages": langs})
            C.update_config_file(config_file(), "logging", {"enabled": self.logging.isChecked(),
                                                            "save_snapshots": self.snapshots.isChecked()})
        except (C.UserError, OSError) as error:
            show_error(self, str(error))
            return
        self.saved.setText("Saved." + (" Stop and start counting to use the new settings."
                                       if self.win.worker.running() else ""))

    def _open_config(self):
        path = config_file()
        if not path.exists():
            try:
                C.update_config_file(path, "live", {})          # create it from config.example.toml, comments included
            except (C.UserError, OSError) as error:
                show_error(self, str(error))
                return
        open_path(path)


class HelpPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        layout = page_layout(self, "Help & diagnostics", None)
        box, box_layout = card("Set up OBS in two minutes")
        steps = [
            "1.  In OBS, make a scene that shows only your gameplay (no webcam or alerts) and click Start Virtual Camera.",
            "2.  Here, pick \"OBS Virtual Camera\" as the video source and click Start counting.",
            "3.  In your stream scene, add a Text (GDI+) source with \"Read from file\" pointing to the file shown on the "
            "Overlay page.",
            "Capture card or second PC? The guide explains every setup.",
        ]
        for step in steps:
            box_layout.addWidget(label(step, wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Open the full guide", on_click=self._guide))
        row.addStretch(1)
        box_layout.addLayout(row)
        layout.addWidget(box)

        box, box_layout = card("Diagnostics", "A short report about this PC's video devices, OBS Virtual Camera and the "
                                              "program files. It contains no account or personal data.")
        row = QHBoxLayout()
        self.run = button("Run diagnostics", "primary", on_click=self._run)
        row.addWidget(self.run)
        self.copy = button("Copy report", on_click=self._copy)
        self.copy.setEnabled(False)
        row.addWidget(self.copy)
        row.addWidget(button("Open logs folder", on_click=win.open_logs))
        row.addStretch(1)
        box_layout.addLayout(row)
        self.report = QPlainTextEdit()
        self.report.setObjectName("report")
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(260)
        self.report.setPlaceholderText("The report appears here.")
        box_layout.addWidget(self.report)
        layout.addWidget(box)

        box, box_layout = card("About")
        box_layout.addWidget(label(f"{APP_NAME} v{__version__} ({RELEASE_CHANNEL}). {TAGLINE}.", wrap=True))
        box_layout.addWidget(label("Free and open source (MIT licence). Not affiliated with or endorsed by Epic Games. "
                                   "It only looks at your video; it never touches the game.", "hint", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Project page", "link", on_click=lambda: QDesktopServices.openUrl(QUrl(REPO_URL))))
        row.addStretch(1)
        box_layout.addLayout(row)
        layout.addWidget(box)
        layout.addStretch(1)
        self._thread = None
        self._result = None
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check)

    def _guide(self):
        guide = paths.APP_DIR / "README.html"
        if guide.exists():
            open_path(guide)
        else:
            QDesktopServices.openUrl(QUrl(REPO_URL + "#readme"))

    def _run(self):
        self.run.setEnabled(False)
        self.report.setPlainText("Running diagnostics (a few seconds)...")

        def work():
            try:
                self._result = run_command(["diagnostics"], timeout=90)[1]
            except Exception as error:
                self._result = f"Diagnostics could not run: {error}"

        self._result = None
        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        self._poll.start(200)

    def _check(self):
        if self._result is None:
            return
        self._poll.stop()
        self.report.setPlainText(self._result.strip())
        self.run.setEnabled(True)
        self.copy.setEnabled(True)

    def _copy(self):
        QApplication.clipboard().setText(self.report.toPlainText())
        self.copy.setText("Copied")
        QTimer.singleShot(1500, lambda: self.copy.setText("Copy report"))


# ==================================================================
# main window
# ==================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1120, 800)
        self.setMinimumSize(920, 640)
        self.worker = Worker()
        self.mode = "stopped"
        self.counts = (0, 0)
        self.entries = deque(maxlen=LOG_LIMIT)
        self.connected = None
        self.started_at = None
        self.last_status = None
        self.error_seen = False
        self.quit_when_stopped = False
        self.sources = []
        self._source_scan = None
        self._state_mtime = None
        try:
            self.preview_reader = PreviewReader(block_name(uuid.uuid4().hex[:12]))
        except Exception:
            self.preview_reader = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.slow = QTimer(self)
        self.slow.timeout.connect(self._tick_slow)
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._tick_preview)

        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())
        self.pages = QStackedWidget()
        self.dashboard = Dashboard(self)
        self.overlay = OverlayPage(self)
        self.settings_page = SettingsPage(self)
        self.help = HelpPage(self)
        for page in (self.dashboard, self.overlay, self.settings_page, self.help):
            self.pages.addWidget(page)
        outer.addWidget(self.pages, 1)
        self.setCentralWidget(root)

        self.dashboard.show_log.setChecked(True)
        self.dashboard.show_preview.setChecked(False)
        self.dashboard._panels()
        self.set_mode("stopped")
        self.read_state(force=True)
        if not C.counter_is_running(paths.APP_DIR / load_cfg()[0]["state"]["path"]):
            self.write_obs_files(quiet=True)          # a fresh unzip/update carries zero placeholders
        self.overlay.load()
        self.settings_page.load()
        self.refresh_viewers()
        self.refresh_sources()
        cfg, warnings = load_cfg()
        for warning in warnings:
            self.add_log({"type": "warn", "text": warning})

        self.timer.start(50)
        self.slow.start(1000)

    # ---- layout
    def _sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(214)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 18, 0, 14)
        layout.setSpacing(6)
        brand = QHBoxLayout()
        brand.setContentsMargins(18, 0, 12, 10)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(ASSETS / "icon_64.png")).scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label("Chest Counter", "brandName"))
        names.addWidget(label("Fortnite Visual", "brandSub"))
        brand.addLayout(names, 1)
        layout.addLayout(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        for name in ("Dashboard", "Overlay", "Settings", "Help & diagnostics"):
            QListWidgetItem(name, self.nav)
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self._page_changed)
        layout.addWidget(self.nav, 1)
        version = label(f"v{__version__} · {RELEASE_CHANNEL}", "version")
        version.setContentsMargins(20, 0, 0, 0)
        layout.addWidget(version)
        return side

    def go_to(self, index):
        self.nav.setCurrentRow(index)

    def _page_changed(self, index):
        self.pages.setCurrentIndex(index)
        if index == 1:
            self.overlay.load()
        elif index == 2:
            self.settings_page.load()

    # ---- sources
    def refresh_sources(self):
        if self._source_scan is not None and self._source_scan.is_alive():
            return
        self.dashboard.refresh.setEnabled(False)
        self.dashboard.source_hint.setText("Looking for video devices...")
        self._scan_result = None

        def scan():
            from fortnite_chest_counter.input import video_sources as sources
            devices, monitors = [], []
            try:
                devices = [n for n, k in sources.list_video_devices() if k in ("video", "none")]
            except Exception:
                pass
            try:
                monitors = sources.list_monitors()
            except Exception:
                pass
            self._scan_result = (devices, monitors)

        self._source_scan = threading.Thread(target=scan, daemon=True)
        self._source_scan.start()

    def _fill_sources(self, devices, monitors):
        cfg, _ = load_cfg()
        live = cfg["live"]
        items = [("OBS Virtual Camera   (recommended)", {"source": "obs-camera"})]
        names = [n for n in devices if n != "OBS Virtual Camera"]
        if live["source"] == "device" and live["device"] not in names and live["device"] != "OBS Virtual Camera":
            names.append(live["device"])
        for name in names:
            missing = "" if name in devices else "   (not found right now)"
            items.append((f"Capture device:  {name}{missing}", {"source": "device", "device": name}))
        for i, (_, _, w, h) in enumerate(monitors, 1):
            items.append((f"Screen {i}   ·   {w} x {h}", {"source": "desktop", "monitor": i}))
        dev_video = os.environ.get("FCC_DEV_VIDEO")
        if dev_video:
            items.append((f"Test video (real time):  {Path(dev_video).name}", {"source": "file", "video": dev_video}))
        current = self.dashboard.source.currentData()
        self.dashboard.source.blockSignals(True)
        self.dashboard.source.clear()
        for text, data in items:
            self.dashboard.source.addItem(text, data)
        wanted = current or {"source": live["source"], "device": live["device"], "monitor": live["monitor"]}
        index = 0
        for i, (_, data) in enumerate(items):
            if data["source"] == wanted.get("source") and all(data[k] == wanted.get(k) for k in data if k != "source"):
                index = i
                break
        self.dashboard.source.setCurrentIndex(index)
        self.dashboard.source.blockSignals(False)
        obs = "OBS Virtual Camera" in devices
        self.dashboard.source_hint.setText(
            "" if obs or not devices else
            "OBS Virtual Camera was not found: open OBS Studio (28 or newer) and click Start Virtual Camera.")
        if not devices and not obs:
            self.dashboard.source_hint.setText("No video devices found. For the recommended setup, open OBS Studio and "
                                               "click Start Virtual Camera, then click Refresh.")
        self.dashboard.refresh.setEnabled(True)

    # ---- counting
    def toggle_counting(self):
        if self.worker.running():
            self.stop_counting()
        else:
            self.start_counting()

    def start_counting(self):
        data = self.dashboard.source.currentData()
        if not data or self.worker.running():
            return
        argv = ["live", "--gui"]
        if self.preview_reader is not None:
            argv += ["--preview", self.preview_reader.name]
        if data["source"] == "file":                                 # developers: FCC_DEV_VIDEO (+ FCC_DEV_VIDEO_START)
            argv += ["--source", "file", "--video", data["video"]]
            if os.environ.get("FCC_DEV_VIDEO_START"):
                argv += ["--start", os.environ["FCC_DEV_VIDEO_START"]]
        else:
            values = {"source": data["source"]}
            if data["source"] == "device":
                values["device"] = data["device"]
            if data["source"] == "desktop":
                values["monitor"] = data["monitor"]
            try:
                C.update_config_file(config_file(), "live", values)   # the console version starts the same way
            except (C.UserError, OSError) as error:
                show_error(self, f"Could not save the video source choice: {error}")
                return
        self.dashboard.banner.hide()
        self.error_seen = False
        self.connected = None
        self.last_status = None
        try:
            self.worker.start(argv)
        except OSError as error:
            show_error(self, f"The counter could not start ({error}). Extract the whole zip again and keep every file "
                             "and folder together.")
            return
        self.add_log({"type": "info", "text": f"Starting: {self.dashboard.source.currentText().split('   ')[0]} ..."})
        self.set_mode("connecting")

    def stop_counting(self):
        if self.worker.running():
            self.set_mode("stopping")
            self.worker.stop()
            QTimer.singleShot(10000, self._stop_timeout)

    def _stop_timeout(self):
        if self.mode == "stopping" and self.worker.running():
            self.worker.kill()          # counts are saved after every chest; this only skips the final summary

    def set_mode(self, mode):
        self.mode = mode
        d = self.dashboard
        text, color = {"stopped": ("Not counting", theme.MUTED), "connecting": ("Connecting", theme.INFO),
                       "counting": ("Counting", theme.CERTAIN), "stopping": ("Stopping", theme.APPROX),
                       "error": ("Not counting", theme.REJECT)}[mode]
        d.set_pill(text, color)
        running = mode in ("connecting", "counting", "stopping")
        d.start.setText({"connecting": "Cancel", "counting": "Stop counting", "stopping": "Stopping..."}.get(mode, "Start counting"))
        restyle(d.start, "danger" if mode in ("connecting", "counting") else "primary")
        d.start.setEnabled(mode != "stopping")
        d.source.setEnabled(not running)
        d.refresh.setEnabled(not running)
        d.analyse.setEnabled(not running)
        if mode == "counting":
            self.started_at = time.monotonic()
        if not running:
            self.started_at = None
            d.metrics.setText("Not counting.")
            d.preview.clear()
        self.preview_visibility_changed()

    def _tick(self):
        if self._source_scan is not None and self._scan_result is not None:
            devices, monitors = self._scan_result
            self._scan_result = None
            self._source_scan = None
            self._fill_sources(devices, monitors)
        for message in self.worker.drain():
            self.handle(message)

    def handle(self, message):
        kind = message.get("type")
        self.add_log(message)
        if kind == "connected":
            self.connected = message
            self.set_mode("counting")
            self.add_log({"type": "info", "text": "Counting. Chests are saved the moment they are counted."
                          + ("" if message.get("persist", True) else " (Saving is turned off in config.toml.)")})
        elif kind in ("counts", "event", "status", "progress"):
            if message.get("certain") is not None and message.get("approx") is not None:
                self.set_counts(message["certain"], message["approx"], flash=kind == "event")
            if kind == "status":
                self.last_status = message
            if kind == "counts" and message.get("overlay") is not None:
                self.dashboard.viewers.setText(message["overlay"].replace("\n", "   /   "))
        elif kind == "error":
            self.error_seen = True
            self.dashboard.show_banner(str(message.get("text", "")))
        elif kind == "stopped":
            minutes = (message.get("seconds") or 0) / 60
            self.add_log({"type": "line", "text": f"Stopped ({message.get('stop_reason', '')}). Analysed "
                          f"{message.get('frames_processed', 0):,} frames in {minutes:.1f} min, "
                          f"{message.get('frames_dropped', 0):,} skipped."})
        elif kind == "exit":
            code = message.get("code")
            if code not in (0, None) and not self.error_seen:
                tail = "\n".join(self.worker.stderr_tail[-6:])
                self.dashboard.show_banner("The counter stopped unexpectedly. Your counts are safe (they are saved after "
                                           "every chest). If it keeps happening, run Help & diagnostics and send the report "
                                           "and the logs folder." + (f"\n\n{tail}" if tail else ""))
                self.error_seen = True
            self.set_mode("error" if self.error_seen else "stopped")
            self.read_state(force=True)
            if self.quit_when_stopped:
                self.close()

    def set_counts(self, certain, approx, flash=False):
        changed = (certain, approx) != self.counts
        self.counts = (certain, approx)
        self.dashboard.certain.set_value(certain, flash=flash and changed)
        self.dashboard.approx.set_value(approx, flash=flash and changed)
        if changed:
            self.refresh_viewers()

    def refresh_viewers(self):
        cfg, _ = load_cfg()
        text = C.overlay_text(cfg["display"], {"certain": self.counts[0], "approximate": self.counts[1]})
        self.dashboard.viewers.setText(text.replace("\n", "   /   "))

    def read_state(self, force=False):
        cfg, _ = load_cfg()
        path = paths.APP_DIR / cfg["state"]["path"]
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        if not force and mtime == self._state_mtime:
            return
        self._state_mtime = mtime
        counts = read_counts(path)
        self.set_counts(*(counts or (0, 0)))

    def write_obs_files(self, quiet=False):
        """The OBS text files from the saved counter (e.g. after an update replaced them with zero placeholders)."""
        try:
            cfg, _ = load_cfg()
            C.preflight(cfg, needs_video=False)
            session = C.CounterSession(cfg)
            session.write_obs()
        except (C.UserError, OSError) as error:
            if not quiet:
                show_error(self, str(error))

    def _tick_slow(self):
        if not self.worker.running():
            self.read_state()
        elif self.mode == "counting" and self.started_at is not None:
            elapsed = int(time.monotonic() - self.started_at)
            parts = [f"Counting for {elapsed // 3600}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}"]
            c = self.connected or {}
            if c.get("resolution"):
                parts.append(f"video {c['resolution'][0]} x {c['resolution'][1]}"
                             + (f" @ {c['input_fps']:g} fps" if c.get("input_fps") else ""))
            s = self.last_status
            if s:
                parts.append(f"analysing {s['fps']:.1f} pictures/s")
                parts.append(f"{s['ms_per_frame']:.0f} ms each")
                if s.get("dropped"):
                    parts.append(f"{fmt(s['dropped'])} skipped")
            self.dashboard.metrics.setText("   ·   ".join(parts))

    # ---- activity log
    def add_log(self, message):
        for debug_only, html in log_entries(message):
            self.entries.append((debug_only, html))
            if not debug_only or self.verbosity() == "debug":
                self.dashboard.log.appendHtml(html)

    def verbosity(self):
        return self.dashboard.detail.currentData()

    def render_log(self):
        log = self.dashboard.log
        log.clear()
        debug = self.verbosity() == "debug"
        for debug_only, html in self.entries:
            if debug or not debug_only:
                log.appendHtml(html)

    def clear_log(self):
        self.entries.clear()
        self.dashboard.log.clear()

    def open_logs(self):
        cfg, _ = load_cfg()
        folder = paths.APP_DIR / cfg["logging"]["dir"]
        folder.mkdir(parents=True, exist_ok=True)
        open_path(folder)

    # ---- preview
    def preview_visibility_changed(self):
        wanted = (self.preview_reader is not None and self.dashboard.show_preview.isChecked()
                  and self.mode in ("connecting", "counting"))
        if self.preview_reader is not None:
            self.preview_reader.set_wanted(wanted)
        if wanted:
            self.preview_timer.start(1000 // 8)
        else:
            self.preview_timer.stop()

    def _tick_preview(self):
        frame = self.preview_reader.read()
        if frame is not None:
            _, width, height, data = frame
            self.dashboard.preview.show_frame(width, height, data)

    # ---- counter actions
    def _cfg_for_actions(self):
        cfg, _ = load_cfg()
        for section, key in (("state", "path"), ("state", "obs_dir"), ("logging", "dir")):
            cfg[section][key] = str(paths.APP_DIR / cfg[section][key])
        return cfg

    def edit_counts(self):
        dialog = CountsDialog(self, *self.counts)
        if dialog.exec() != QDialog.Accepted:
            return
        self._set(dialog.certain.value(), dialog.approx.value(), "set_count")

    def reset_counts(self):
        if ask(self, "Reset the counter?", "Set both counts to 0? This cannot be undone.", "Reset to 0", danger=True):
            self._set(0, 0, "reset")

    def _set(self, certain, approx, action):
        try:
            session = C.set_counts(self._cfg_for_actions(), certain, approx, action)
        except (C.UserError, OSError) as error:
            show_error(self, str(error))
            return
        self.set_counts(session.state["certain"], session.state["approximate"], flash=True)
        what = "reset to 0" if action == "reset" else f"set to CERTAIN {fmt(certain)} / APPROX {fmt(approx)}"
        self.add_log({"type": "info", "text": f"Counter {what}."
                      + (" The running counter picks it up within a second." if self.worker.running() else "")})

    def analyse_video(self):
        if self.worker.running():
            return
        VideoDialog(self).exec()

    # ---- closing
    def closeEvent(self, event):
        if self.worker.running():
            if not self.quit_when_stopped:
                if not ask(self, "Stop counting?", "The counter is running. Stop counting and close the app?\n\n"
                                                   "Your counts are saved and kept for next time.", "Stop and close"):
                    event.ignore()
                    return
                self.quit_when_stopped = True
                self.stop_counting()
                self.hide()
            event.ignore()                       # closes for real when the worker has finished (see handle 'exit')
            return
        if self.preview_reader is not None:
            self.preview_reader.close()
        super().closeEvent(event)
        QApplication.quit()


# ==================================================================
# start-up
# ==================================================================

def _crash_hook(window_ref):
    def hook(kind, value, tb):
        where = None
        try:
            folder = paths.APP_DIR / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            where = folder / f"crash_app_{datetime.now():%Y%m%d_%H%M%S}.txt"
            where.write_text(f"{APP_NAME} v{__version__} (app window)\n\n" + "".join(traceback.format_exception(kind, value, tb)),
                             encoding="utf-8")
        except OSError:
            pass
        try:
            QMessageBox.critical(window_ref(), APP_NAME,
                                 f"Something unexpected went wrong in the app window ({kind.__name__}: {value}).\n\n"
                                 "Counting is not affected: it runs separately and saves after every chest."
                                 + (f"\n\nDetails were saved to:\n{where}" if where else ""))
        except Exception:
            pass
    return hook


def _single_instance():
    """One app window per program folder. -> a handle to keep, or None if another window is already open."""
    try:
        import hashlib
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        name = "Local\\FortniteVisualChestCounter-App-" + hashlib.sha1(str(paths.APP_DIR).lower().encode()).hexdigest()[:16]
        handle = k.CreateMutexW(None, False, name)
        if handle and ctypes.get_last_error() == 183:
            return None
        return handle or True
    except Exception:
        return True


def _palette():
    palette = QPalette()
    for role, color in ((QPalette.Window, theme.BG), (QPalette.WindowText, theme.TEXT), (QPalette.Base, theme.SURFACE_2),
                        (QPalette.AlternateBase, theme.SURFACE), (QPalette.Text, theme.TEXT), (QPalette.Button, theme.SURFACE_2),
                        (QPalette.ButtonText, theme.TEXT), (QPalette.Highlight, theme.ACCENT), (QPalette.HighlightedText, "#ffffff"),
                        (QPalette.ToolTipBase, theme.SURFACE_3), (QPalette.ToolTipText, theme.TEXT),
                        (QPalette.PlaceholderText, theme.DIM), (QPalette.Link, theme.ACCENT)):
        palette.setColor(role, QColor(color))
    return palette


def self_test(app, report_path):
    """`--self-test REPORT.json`: build the real window without ever showing it, wait for the device scan, save a
    screenshot next to the report and exit. Proves the whole start chain (launcher -> pythonw -> Qt -> window) works on a
    PC without anything appearing on screen."""
    report_path = Path(report_path)
    result = {"ok": False, "version": __version__, "python": sys.version.split()[0], "executable": sys.executable,
              "app_dir": str(paths.APP_DIR), "packaged": paths.PACKAGED}
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        result.update(pyside=PySide6.__version__, qt=qVersion(), platform=app.platformName())
        window = MainWindow()
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        window.show()
        deadline = time.monotonic() + 20
        while window.dashboard.source.count() == 0 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)
        for _ in range(10):
            app.processEvents()
            time.sleep(0.02)
        result["sources"] = [window.dashboard.source.itemText(i) for i in range(window.dashboard.source.count())]
        result["screenshot"] = str(report_path.with_suffix(".png"))
        result["ok"] = bool(window.grab().save(result["screenshot"])) and bool(result["sources"])
        window.preview_reader and window.preview_reader.close()
    except Exception:
        result["error"] = traceback.format_exc()
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


def main(argv=None):
    paths.setup_environment()                     # run from the program folder; bundled ffmpeg first
    paths.HIDE_CHILD_CONSOLES = True
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)    # own taskbar icon/group
    except Exception:
        pass
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setStyleSheet(theme.STYLE)
    if len(args) == 2 and args[0] == "--self-test":
        return self_test(app, args[1])
    lock = _single_instance()
    if lock is None:
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already open.\n\nLook for it in the taskbar.")
        return 0
    window = MainWindow()
    sys.excepthook = _crash_hook(lambda: window)
    window.show()
    return app.exec()
