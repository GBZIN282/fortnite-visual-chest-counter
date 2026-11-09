"""Colours and the Qt style sheet of the desktop app (one dark theme, in the spirit of OBS)."""

BG = "#111318"
SIDEBAR = "#0b0d11"
SURFACE = "#191c23"
SURFACE_2 = "#20242d"
SURFACE_3 = "#2a2f3a"
BORDER = "#2b303b"
TEXT = "#e8eaee"
MUTED = "#8c94a4"
DIM = "#5f6776"
ACCENT = "#5b8cff"
ACCENT_HOVER = "#7aa2ff"
CERTAIN = "#34d399"
APPROX = "#fbbf24"
REJECT = "#f87171"
DANGER = "#ef4444"
WARN = "#c084fc"
INFO = "#67c7e8"

LOG_COLORS = {"certain": CERTAIN, "approx": APPROX, "rejected": REJECT, "generic": DIM, "info": INFO, "warn": WARN,
              "error": REJECT, "line": MUTED, "status": DIM, "detail": DIM}

STYLE = f"""
* {{ font-family: "Segoe UI", "Segoe UI Variable Text", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog, #page {{ background: {BG}; }}
QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}

#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
#brandName {{ font-size: 11pt; font-weight: 600; }}
#brandSub {{ color: {MUTED}; font-size: 8.5pt; }}
#nav {{ background: transparent; border: none; outline: none; }}
#nav::item {{ padding: 9px 12px; margin: 2px 8px; border-radius: 6px; color: {MUTED}; }}
#nav::item:hover {{ background: {SURFACE}; color: {TEXT}; }}
#nav::item:selected {{ background: {SURFACE_2}; color: {TEXT}; }}
#version {{ color: {DIM}; font-size: 8.5pt; }}

#pageTitle {{ font-size: 17pt; font-weight: 600; }}
#pageSub {{ color: {MUTED}; }}
#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
#cardTitle {{ font-weight: 600; font-size: 10.5pt; }}
#hint, .hint {{ color: {MUTED}; font-size: 9pt; }}
#metrics {{ color: {MUTED}; font-size: 9pt; }}

#countCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#countLabel {{ color: {MUTED}; font-size: 9pt; font-weight: 600; letter-spacing: 1px; }}
#countValue {{ font-size: 40pt; font-weight: 700; }}
#countSub {{ color: {MUTED}; font-size: 9pt; }}

#pill {{ border-radius: 11px; padding: 3px 12px; font-size: 9pt; font-weight: 600; }}
#banner {{ background: #3a1d22; border: 1px solid #6b2a33; border-radius: 8px; }}
#bannerText {{ color: #ffd7dc; }}
#notice {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; }}
#overlayBox {{ background: #000000; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 14px;
               font-family: "Segoe UI"; font-size: 15pt; font-weight: 700; color: #ffffff; }}

QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 7px; padding: 7px 14px; }}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {DIM}; background: {SURFACE}; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600; padding: 9px 22px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {SURFACE_3}; border-color: {SURFACE_3}; color: {MUTED}; }}
QPushButton#danger {{ background: {DANGER}; border: 1px solid {DANGER}; color: white; font-weight: 600; padding: 9px 22px; }}
QPushButton#danger:hover {{ background: #f05a5a; }}
QPushButton#toggle {{ background: transparent; border: 1px solid {BORDER}; border-radius: 14px; padding: 5px 14px; color: {MUTED}; }}
QPushButton#toggle:checked {{ background: {SURFACE_2}; color: {TEXT}; border-color: {ACCENT}; }}
QPushButton#link {{ background: transparent; border: none; color: {ACCENT}; padding: 0; }}
QPushButton#link:hover {{ color: {ACCENT_HOVER}; text-decoration: underline; }}

QComboBox, QLineEdit, QSpinBox {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 10px;
                                  selection-background-color: {ACCENT}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {SURFACE_3};
                              outline: none; padding: 4px; }}
QLineEdit:read-only {{ color: {MUTED}; }}

QCheckBox, QRadioButton {{ spacing: 8px; padding: 3px 0; }}

QPlainTextEdit#log, QPlainTextEdit#report {{ background: #0c0e12; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px;
                                            font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9pt; }}
#previewBox {{ background: #000000; border: 1px solid {BORDER}; border-radius: 8px; color: {DIM}; }}

QProgressBar {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px; height: 12px; text-align: center;
                color: {TEXT}; font-size: 8.5pt; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SURFACE_3}; border-radius: 4px; min-width: 30px; }}
QSplitter::handle {{ background: transparent; }}
QMessageBox QLabel {{ min-width: 340px; }}
"""


def rgba(color, alpha):
    """'#rrggbb' + opacity 0..1 -> 'rgba(r, g, b, a)'. (Qt reads 8-digit hex as #AARRGGBB, so never append alpha.)"""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {round(alpha * 255)})"


def pill_style(color):
    """Status pill: tinted background, coloured text."""
    return f"background: {rgba(color, 0.13)}; color: {color}; border: 1px solid {rgba(color, 0.35)};"
