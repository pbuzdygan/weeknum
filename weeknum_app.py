import json
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRect, QPoint, QSize, QSettings, QEvent, QPointF, QUrl
from PySide6.QtGui import (
    QDesktopServices, QIcon, QAction, QKeyEvent, QPixmap, QPainter, QFont, QColor, QCursor, QPolygonF, QPen, QPainterPath
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGridLayout, QFrame, QDialog, QStyle,
    QComboBox, QSpinBox, QAbstractSpinBox,
    QToolTip, QSizePolicy
)

APP_ORG = "WeekNum"
APP_NAME = "WeekNumApp"
APP_VERSION = "1.3.0"

UPDATE_API_URL = "https://api.github.com/repos/pbuzdygan/weeknum/releases/latest"
UPDATE_LATEST_URL = "https://github.com/pbuzdygan/weeknum/releases/latest"


def parse_semver(v: str) -> tuple[int, int, int] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))

def resource_path(*parts: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base.joinpath(*parts))

def _autostart_registry_name() -> str:
    return APP_NAME

def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f"\"{sys.executable}\""
    script_path = str(Path(__file__).resolve())
    return f"\"{sys.executable}\" \"{script_path}\""

def get_windows_autostart_enabled() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _autostart_registry_name())
        return True
    except Exception:
        return False

def set_windows_autostart_enabled(enabled: bool) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            name = _autostart_registry_name()
            if enabled:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False

# Typography (Fluent-like)
# Qt's text rendering can be uneven with variable fonts on Windows.
# Use the non-variable Segoe UI to keep weights consistent.
FONT_FAMILY = "Segoe UI"
FONT_HEADLINE_PX = 24  # Headline / Clock: 24px SemiBold
FONT_BODY_PX = 12      # Body / Date: 12px Regular
FONT_DAY_PX = 15       # Calendar days: 13px Regular
FONT_LABEL_PX = 13     # Week days + WXX + Q Labels: 11px Regular
FONT_HEADER_PX = 16    # Month/Year header text
FONT_NAV_PX = 16       # Nav arrows


# ---------------- Windows theme (light/dark) + accent color ----------------
def _read_reg_dword(root, subkey: str, name: str, default: int | None = None) -> int | None:
    try:
        import winreg
        with winreg.OpenKey(root, subkey) as k:
            v, t = winreg.QueryValueEx(k, name)
            if isinstance(v, int):
                return v
    except Exception:
        pass
    return default

def windows_apps_use_light_theme() -> bool:
    """
    True = light, False = dark.
    Reads Windows personalization registry:
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize\\AppsUseLightTheme
    """
    try:
        import winreg
        val = _read_reg_dword(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "AppsUseLightTheme",
            default=1,
        )
        return bool(val)
    except Exception:
        return True

def windows_accent_color(default: QColor = QColor(0, 120, 212)) -> QColor:
    """
    Best-effort accent color read.
    Common keys:
      HKCU\\Software\\Microsoft\\Windows\\DWM\\ColorizationColor (ARGB)
    If unavailable, fall back to Win-blue.
    """
    try:
        import winreg
        v = _read_reg_dword(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\DWM",
            "ColorizationColor",
            default=None,
        )
        if v is None:
            return default
        # v is ARGB in a DWORD: 0xAARRGGBB
        a = (v >> 24) & 0xFF
        r = (v >> 16) & 0xFF
        g = (v >> 8) & 0xFF
        b = v & 0xFF
        # Sometimes alpha is low; clamp to opaque-ish for UI
        a = max(a, 0xC0)
        return QColor(r, g, b, a)
    except Exception:
        return default

@dataclass(frozen=True)
class Theme:
    mode: str            # "light" or "dark"
    accent: QColor

def detect_theme() -> Theme:
    light = windows_apps_use_light_theme()
    mode = "light" if light else "dark"
    accent = windows_accent_color()
    return Theme(mode=mode, accent=accent)

def text_color_for_bg(bg: QColor) -> QColor:
    # WCAG-ish luminance check to pick a contrasting text color.
    r, g, b = bg.red(), bg.green(), bg.blue()
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return QColor(0, 0, 0) if luminance > 0.6 else QColor(255, 255, 255)

# ---------------- Tray icon: readable "xx" without background ----------------
def make_week_icon(
    week: int,
    text_color: QColor | None = None,
) -> QIcon:
    """
    Tray icon: large, readable "xx" text without a background.
    """
    txt = f"{week:02d}"

    def draw(size: int) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        pad = 0
        rect = QRect(pad, pad, size - pad * 2, size - pad * 2)

        # Fit text dynamically into the available area
        target = rect.adjusted(pad, pad, -pad, -pad)
        font = QFont(FONT_FAMILY)
        font.setBold(False)
        font_size = int(size * 1.15)
        font.setPixelSize(font_size)
        p.setFont(font)
        fm = p.fontMetrics()
        text_rect = fm.tightBoundingRect(txt)
        while (text_rect.width() > target.width() or text_rect.height() > target.height()) and font_size > 6:
            font_size -= 1
            font.setPixelSize(font_size)
            p.setFont(font)
            fm = p.fontMetrics()
            text_rect = fm.tightBoundingRect(txt)

        # Plain text, no outline
        # Note: AlignCenter can ignore negative glyph bearings at small sizes, causing edge clipping.
        # Center horizontally using the tight bounds (prevents "0" left clipping),
        # but center vertically using the looser bounds (looks more visually centered).
        p.setPen(text_color if text_color is not None else QColor(0, 0, 0))
        tight = text_rect
        loose = fm.boundingRect(txt)
        target_center = QPointF(target.center())
        pos = QPointF(
            target_center.x() - QPointF(tight.center()).x(),
            target_center.y() - QPointF(loose.center()).y(),
        )
        p.drawText(pos, txt)

        p.end()
        return pm

    icon = QIcon()
    for s in (16, 20, 24, 28, 32, 40, 48, 64, 96, 128):
        icon.addPixmap(draw(s))
    return icon


def make_filled_triangle_icon(direction: str, color: QColor) -> QIcon:
    """
    Crisp, filled left/right triangle icon.
    Using font glyphs (◀/▶) can look jagged depending on font fallback/hinting.
    """
    if direction not in ("left", "right"):
        raise ValueError("direction must be 'left' or 'right'")

    def draw(size: int, scale: int) -> QPixmap:
        pm = QPixmap(size * scale, size * scale)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(color)

        m = size * 0.16  # margin
        if direction == "left":
            pts = [
                QPointF(size - m, m),
                QPointF(size - m, size - m),
                QPointF(m, size / 2),
            ]
        else:
            pts = [
                QPointF(m, m),
                QPointF(m, size - m),
                QPointF(size - m, size / 2),
            ]

        p.drawPolygon(QPolygonF(pts))
        p.end()
        return pm

    icon = QIcon()
    for size in (14, 16, 18, 20, 24):
        for scale in (1, 2):
            icon.addPixmap(draw(size, scale))
    return icon


def make_checkmark_pixmap(color: QColor, size: int = 14) -> QPixmap:
    """
    Crisp checkmark for menu items (avoids jagged font glyph rendering).
    """
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(size * 0.16)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    path = QPainterPath()
    path.moveTo(size * 0.18, size * 0.55)
    path.lineTo(size * 0.42, size * 0.74)
    path.lineTo(size * 0.82, size * 0.26)
    p.drawPath(path)
    p.end()
    return pm


# ---------------- ISO helpers ----------------
def iso_week(d: date) -> int:
    return d.isocalendar().week

def start_of_iso_week(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday=0

def month_grid_start(year: int, month: int) -> date:
    return start_of_iso_week(date(year, month, 1))


ENG_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class State:
    year: int
    month: int


def build_styles(theme: Theme) -> dict[str, str]:
    """
    Returns style sheets for: calendar, info dialog, menu.
    Keep them in sync across light/dark.
    """
    accent = theme.accent
    accent_rgb = f"{accent.red()},{accent.green()},{accent.blue()}"
    accent_tuple = (accent.red(), accent.green(), accent.blue())

    def blend(bg: tuple[int, int, int], fg: tuple[int, int, int], t: float) -> str:
        r = round(bg[0] * (1 - t) + fg[0] * t)
        g = round(bg[1] * (1 - t) + fg[1] * t)
        b = round(bg[2] * (1 - t) + fg[2] * t)
        return f"rgb({r},{g},{b})"

    if theme.mode == "dark":
        shell_bg_rgb = (32, 32, 32)
        shell_bg = "rgb(32,32,32)"
        border = "rgba(255,255,255,0.10)"
        text_primary = "#ffffff"
        text_secondary = "#ffffff"
        dim_text = "rgba(255,255,255,0.42)"
        weekend_text = "rgb(255,151,151)"
        hover = blend(shell_bg_rgb, accent_tuple, 0.22)
        press = blend(shell_bg_rgb, accent_tuple, 0.32)
        today_bg = f"rgb({accent_rgb})"
        today_text_qc = text_color_for_bg(accent)
        today_text = f"rgb({today_text_qc.red()},{today_text_qc.green()},{today_text_qc.blue()})"
        cell_hover = blend(shell_bg_rgb, accent_tuple, 0.30)
        month_panel_bg = "rgba(255,255,255,0.04)"
        month_panel_border = "rgba(255,255,255,0.12)"
        header_bg = "rgba(255,255,255,0.03)"
        header_sep = "rgba(255,255,255,0.14)"
        menu_bg = "#202020"
        menu_border = "rgba(255,255,255,0.14)"
        menu_item_hover = blend((32, 32, 32), accent_tuple, 0.26)
        sep = "rgba(255,255,255,0.10)"
    else:
        shell_bg_rgb = (255, 255, 255)
        shell_bg = "rgb(255,255,255)"
        border = "rgba(0,0,0,0.08)"
        text_primary = "#1f1f1f"
        text_secondary = "#666666"
        dim_text = "rgba(0,0,0,0.34)"
        weekend_text = "rgb(176,56,56)"
        hover = blend(shell_bg_rgb, accent_tuple, 0.10)
        press = blend(shell_bg_rgb, accent_tuple, 0.16)
        today_bg = f"rgb({accent_rgb})"
        today_text_qc = text_color_for_bg(accent)
        today_text = f"rgb({today_text_qc.red()},{today_text_qc.green()},{today_text_qc.blue()})"
        cell_hover = blend(shell_bg_rgb, accent_tuple, 0.18)
        month_panel_bg = "rgba(0,0,0,0.02)"
        month_panel_border = "rgba(0,0,0,0.08)"
        header_bg = "rgba(0,0,0,0.015)"
        header_sep = "rgba(0,0,0,0.10)"
        menu_bg = "#f8f8f8"
        menu_border = "#d0d0d0"
        menu_item_hover = blend((248, 248, 248), accent_tuple, 0.10)
        sep = "#e0e0e0"

    calendar_qss = f"""
        #calendarWindow {{ background: transparent; }}
        #CalendarShell {{
            background: {shell_bg};
            border-radius: 14px;
            border: 1px solid {border};
            font-family: "{FONT_FAMILY}", "Segoe UI";
        }}
        #CalendarCard {{ background: transparent; border: none; }}
        #HeaderRow {{
            background: {header_bg};
            border-radius: 10px;
        }}
        #HeaderSeparator {{
            background: {header_sep};
            min-height: 1px;
            max-height: 1px;
            border: none;
        }}
        #MonthPanel {{
            background: {month_panel_bg};
            border: 1px solid {month_panel_border};
            border-radius: 10px;
        }}

        #CalendarShell QPushButton {{
            font-family: "{FONT_FAMILY}", "Segoe UI";
            font-size: {FONT_BODY_PX}px;
            font-weight: 400;
        }}
        #CalendarShell QLabel {{
            font-family: "{FONT_FAMILY}", "Segoe UI";
            font-size: {FONT_BODY_PX}px;
            font-weight: 400;
        }}

        QPushButton#NavButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 2px 4px; font-size: {FONT_NAV_PX}px; min-width: 22px; min-height: 24px;
            text-align: center;
            color: {text_primary};
        }}
        QPushButton#TodayButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 2px 8px; font-size: {FONT_BODY_PX}px; font-weight: 600; min-height: 24px;
            color: {text_primary};
        }}
        QPushButton#ViewButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 2px 8px; font-size: {FONT_BODY_PX}px; min-height: 24px;
            text-align: center;
            color: {text_primary};
        }}
        QPushButton#PinButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 2px 6px; font-size: {FONT_BODY_PX}px; min-height: 24px; min-width: 24px;
            text-align: center;
            color: {text_primary};
        }}
        QPushButton#PinButton:checked {{ background: {press}; }}
        QComboBox#MonthSelect, QSpinBox#YearSpin {{
            background: transparent;
            border: none;
            border-radius: 8px;
            padding: 2px 6px;
            min-height: 24px;
            color: {text_primary};
        }}
        QComboBox#MonthSelect {{
            font-size: {FONT_BODY_PX}px;
            font-weight: 600;
            min-width: 86px;
        }}
        QSpinBox#YearSpin {{
            font-size: {FONT_BODY_PX}px;
            font-weight: 600;
            min-width: 50px;
            padding-right: 4px;
        }}
        QComboBox#MonthSelect QAbstractItemView {{
            background: {shell_bg};
            color: {text_primary};
            border: 1px solid {border};
            selection-background-color: {hover};
            selection-color: {text_primary};
            outline: none;
        }}
        QComboBox#MonthSelect::drop-down {{
            border: none;
            border-left: 1px solid {border};
            width: 18px;
        }}
        QComboBox#MonthSelect::down-arrow {{
            width: 10px;
            height: 10px;
        }}
        QComboBox#MonthSelect:hover,
        QSpinBox#YearSpin:hover {{
            background: {hover};
        }}

        QPushButton#NavButton:hover,
        QPushButton#TodayButton:hover,
        QPushButton#ViewButton:hover,
        QPushButton#PinButton:hover {{ background: {hover}; }}

        QPushButton#NavButton:pressed,
        QPushButton#TodayButton:pressed,
        QPushButton#ViewButton:pressed,
        QPushButton#PinButton:pressed {{ background: {press}; }}

        QLabel#MonthTitle {{ color: {text_primary}; font-size: {FONT_HEADER_PX}px; font-weight: 600; }}
        QLabel#InfoLabel {{ color: {text_secondary}; font-size: {FONT_BODY_PX}px; font-weight: 400; }}
        QLabel#DowLabel {{ color: {text_secondary}; font-size: {FONT_LABEL_PX}px; font-weight: 400; }}
        QLabel#DowLabel[weekend="true"] {{ color: {weekend_text}; font-weight: 600; }}
        QFrame[cellRole="dow"] {{ border-bottom: 1px solid {border}; border-radius: 0px; }}
        QFrame[cellRole="day"] {{ background: transparent; border-radius: 8px; }}
        QFrame[cellRole="day"]:hover {{ background: {cell_hover}; }}
        QFrame[cellRole="day"][state="today"] {{ background: {today_bg}; }}
        QFrame[cellRole="day"][state="today"]:hover {{ background: {today_bg}; }}

        QLabel#DayLabel {{ font-size: {FONT_DAY_PX}px; font-weight: 400; color: {text_primary}; }}
        QLabel#DayLabel[weekend="true"] {{ color: {weekend_text}; }}
        QLabel#DayLabel[dim="true"] {{ color: {dim_text}; }}
        QLabel#DayLabel[today="true"] {{ color: {today_text}; font-weight: 600; }}

        QFrame[cellRole="week"] {{ background: transparent; border-radius: 6px; }}
        QLabel#WeekLabel {{ font-size: {FONT_LABEL_PX}px; font-weight: 400; color: {text_secondary}; }}
    """

    info_qss = f"""
        QDialog {{ background: transparent; }}
        #InfoShell {{
            background: {shell_bg};
            border-radius: 12px;
            border: 1px solid {border};
            font-family: "{FONT_FAMILY}", "Segoe UI";
        }}
        QLabel#InfoTitle {{ font-size: {FONT_HEADLINE_PX}px; font-weight: 600; color: {text_primary}; }}
        QLabel {{ font-size: {FONT_BODY_PX}px; font-weight: 400; color: {text_secondary}; }}
        QLabel#UpdateStatus {{ font-weight: 600; }}
        QPushButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 6px 10px; font-size: {FONT_BODY_PX}px; font-weight: 400;
            color: {text_primary};
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:pressed {{ background: {press}; }}
    """

    menu_qss = f"""
        FluentMenu {{
            background: transparent;
        }}
        #MenuShell {{
            background: {menu_bg};
            border: 1px solid {menu_border};
            border-radius: 12px;
            font-family: "{FONT_FAMILY}", "Segoe UI";
            font-size: {FONT_BODY_PX}px;
            font-weight: 400;
        }}
        #MenuItem {{
            border-radius: 8px;
            background-color: transparent;
        }}
        #MenuItem:hover {{
            background-color: {menu_item_hover};
        }}
        #MenuText {{
            color: {text_primary};
            font-size: {FONT_BODY_PX}px;
            font-weight: 400;
        }}
        #MenuCheck {{
            color: {text_primary};
            font-size: {FONT_BODY_PX}px;
        }}
        #MenuSeparator {{
            background: {sep};
            margin: 4px 6px;
        }}
    """

    tooltip_qss = f"""
        QToolTip {{
            font-family: "{FONT_FAMILY}", "Segoe UI";
            font-size: {FONT_BODY_PX}px;
            font-weight: 400;
            color: {text_primary};
            background: {shell_bg};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 6px 10px;
        }}
    """

    return {"calendar": calendar_qss, "info": info_qss, "menu": menu_qss, "app": tooltip_qss}


class CalendarWindow(QWidget):
    def __init__(self, state: State, theme: Theme, on_pin_changed=None):
        super().__init__()
        self.state = state
        self._pinned = False
        self._suppress_hide = False
        self._theme = theme
        self._on_pin_changed = on_pin_changed
        self._settings = QSettings(APP_ORG, APP_NAME)
        self._months_count = self._load_months_count()
        self._month_views: list[QWidget] = []

        self.setWindowTitle("Calendar - week numbers")
        self.setObjectName("calendarWindow")
        # Transparent outer window so rounded shell corners don't show a square backdrop
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        # Flyout-like by default (Popup closes on outside click automatically)
        self._apply_window_flags()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("CalendarShell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(10, 8, 10, 8)
        shell_layout.setSpacing(6)
        root.addWidget(self.shell)

        self.header_row = QFrame(self.shell)
        self.header_row.setObjectName("HeaderRow")
        top = QHBoxLayout(self.header_row)
        top.setContentsMargins(4, 1, 4, 1)
        top.setSpacing(3)

        self.prev_btn = QPushButton("")
        self.next_btn = QPushButton("")
        self.prev_btn.setObjectName("NavButton")
        self.next_btn.setObjectName("NavButton")
        self.prev_btn.clicked.connect(self.prev_month)
        self.next_btn.clicked.connect(self.next_month)

        self.month_combo = QComboBox()
        self.month_combo.setObjectName("MonthSelect")
        self.month_combo.addItems(ENG_MONTHS)
        self.month_combo.currentIndexChanged.connect(self._on_month_changed)

        self.year_spin = QSpinBox()
        self.year_spin.setObjectName("YearSpin")
        self.year_spin.setRange(1900, 2200)
        self.year_spin.setAlignment(Qt.AlignCenter)
        self.year_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.year_spin.valueChanged.connect(self._on_year_changed)

        self.prev_year_btn = QPushButton("")
        self.next_year_btn = QPushButton("")
        self.prev_year_btn.setObjectName("NavButton")
        self.next_year_btn.setObjectName("NavButton")
        self.prev_year_btn.clicked.connect(self.prev_year)
        self.next_year_btn.clicked.connect(self.next_year)

        self.today_btn = QPushButton("Today")
        self.today_btn.setObjectName("TodayButton")
        self.today_btn.clicked.connect(self.go_today)

        self.view_btn = QPushButton("")
        self.view_btn.setObjectName("ViewButton")
        self.view_btn.clicked.connect(self.toggle_months_view)

        self.pin_btn = QPushButton("📌")
        self.pin_btn.setObjectName("PinButton")
        self.pin_btn.setCheckable(True)
        self.pin_btn.toggled.connect(self._on_pin_btn_toggled)

        top.addWidget(self.prev_btn)
        top.addWidget(self.next_btn)
        top.addWidget(self.month_combo)
        top.addWidget(self.prev_year_btn)
        top.addWidget(self.year_spin)
        top.addWidget(self.next_year_btn)
        top.addStretch(1)
        top.addWidget(self.today_btn)
        top.addWidget(self.view_btn)
        top.addWidget(self.pin_btn)
        shell_layout.addWidget(self.header_row)

        header_sep = QFrame(self.shell)
        header_sep.setObjectName("HeaderSeparator")
        shell_layout.addWidget(header_sep)

        card = QFrame()
        card.setObjectName("CalendarCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(4, 4, 4, 0)
        card_layout.setSpacing(4)

        self.months_host = QWidget(card)
        self.months_layout = QHBoxLayout(self.months_host)
        self.months_layout.setContentsMargins(0, 0, 0, 0)
        self.months_layout.setSpacing(8)
        card_layout.addWidget(self.months_host, 1)

        self.info_label = QLabel("")
        self.info_label.setObjectName("InfoLabel")
        self.info_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.info_label)

        shell_layout.addWidget(card, 1)

        self.apply_theme(self._theme)
        self._apply_picker_widths()
        self._sync_controls()
        self._update_view_button()
        self._update_window_size()
        self._sync_pin_button()
        self.render()

    def _apply_window_flags(self):
        # Flyout behavior (Popup) unless pinned
        if self._pinned:
            self.setWindowFlags(
                Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
            )
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        else:
            self.setWindowFlags(
                Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
            )

    def apply_theme(self, theme: Theme):
        self._theme = theme
        styles = build_styles(theme)
        self.setStyleSheet(styles["calendar"])
        self._apply_nav_icons()

    def _apply_nav_icons(self):
        color = QColor(255, 255, 255) if self._theme.mode == "dark" else QColor(31, 31, 31)
        icon_size = QSize(12, 12)

        self.prev_btn.setText("")
        self.prev_btn.setIcon(make_filled_triangle_icon("left", color))
        self.prev_btn.setIconSize(icon_size)

        self.next_btn.setText("")
        self.next_btn.setIcon(make_filled_triangle_icon("right", color))
        self.next_btn.setIconSize(icon_size)

        self.prev_year_btn.setText("")
        self.prev_year_btn.setIcon(make_filled_triangle_icon("left", color))
        self.prev_year_btn.setIconSize(icon_size)

        self.next_year_btn.setText("")
        self.next_year_btn.setIcon(make_filled_triangle_icon("right", color))
        self.next_year_btn.setIconSize(icon_size)

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key_Left:
            self.prev_month()
        elif e.key() == Qt.Key_Right:
            self.next_month()
        elif e.key() == Qt.Key_Escape:
            self.hide()

    def changeEvent(self, event):
        # When pinned we keep the window, otherwise behave like flyout.
        if event.type() == QEvent.WindowDeactivate:
            if not self._pinned and not self._suppress_hide and QApplication.activeModalWidget() is None:
                self.reset_to_default()
                self.hide()
        super().changeEvent(event)

    def _load_months_count(self) -> int:
        raw = self._settings.value("calendar/months_count", 1)
        try:
            parsed = int(raw)
        except Exception:
            parsed = 1
        return 3 if parsed == 3 else 1

    def _save_months_count(self):
        self._settings.setValue("calendar/months_count", self._months_count)
        self._settings.sync()

    def _update_view_button(self):
        next_count = 3 if self._months_count == 1 else 1
        self.view_btn.setText(f"{next_count}M")
        self.view_btn.setToolTip(f"Switch to {next_count} month view")

    def _apply_picker_widths(self):
        fm = self.month_combo.fontMetrics()
        max_month_width = max(fm.horizontalAdvance(name) for name in ENG_MONTHS)
        self.month_combo.setFixedWidth(max_month_width + 24)

        year_fm = self.year_spin.fontMetrics()
        year_width = year_fm.horizontalAdvance("2222")
        self.year_spin.setFixedWidth(year_width + 12)

    def _sync_pin_button(self):
        self.pin_btn.blockSignals(True)
        self.pin_btn.setChecked(self._pinned)
        self.pin_btn.blockSignals(False)
        self.pin_btn.setToolTip("Unpin window" if self._pinned else "Pin window")

    def _on_pin_btn_toggled(self, checked: bool):
        self.set_pinned(checked)
        if callable(self._on_pin_changed):
            self._on_pin_changed(bool(checked))

    def _update_window_size(self):
        width = 380 if self._months_count == 1 else 1060
        self.setFixedSize(width, 360)

    def _sync_controls(self):
        self.month_combo.blockSignals(True)
        self.year_spin.blockSignals(True)
        self.month_combo.setCurrentIndex(self.state.month - 1)
        self.year_spin.setValue(self.state.year)
        self.month_combo.blockSignals(False)
        self.year_spin.blockSignals(False)

    def _on_month_changed(self, idx: int):
        self.state.month = idx + 1
        self.render()

    def _on_year_changed(self, year: int):
        self.state.year = year
        self.render()

    def prev_year(self):
        self.state.year -= 1
        self.render()

    def next_year(self):
        self.state.year += 1
        self.render()

    def _month_with_offset(self, year: int, month: int, offset: int) -> tuple[int, int]:
        total = (year * 12 + (month - 1)) + offset
        return total // 12, (total % 12) + 1

    def _clear_month_views(self):
        while self.months_layout.count():
            item = self.months_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._month_views.clear()

    def _set_info_text(self):
        d = date.today()
        self.info_label.setText(f"Week {iso_week(d):02d} · {d.strftime('%A, %d %B %Y')}")

    def _build_month_view(self, year: int, month: int) -> QWidget:
        month_panel = QFrame(self.months_host)
        month_panel.setObjectName("MonthPanel")
        layout = QVBoxLayout(month_panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel(f"{ENG_MONTHS[month - 1]} {year}", month_panel)
        title.setObjectName("MonthTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        grid_widget = QWidget(month_panel)
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        for c in range(8):
            grid.setColumnStretch(c, 1)
        for r in range(7):
            grid.setRowStretch(r, 1)

        grid.addWidget(self.dow_cell("Wk"), 0, 0)
        for col, name in enumerate(DOW, start=1):
            grid.addWidget(self.dow_cell(name, weekend=(col >= 6)), 0, col)

        start = month_grid_start(year, month)
        today = date.today()
        current_week_start = start_of_iso_week(today)
        for r in range(6):
            week_start = start + timedelta(days=7 * r)
            wn = iso_week(week_start)
            is_current_week = (week_start == current_week_start)
            grid.addWidget(self.week_cell(f"{wn:02d}", week_current=is_current_week), r + 1, 0)
            for c in range(7):
                d = week_start + timedelta(days=c)
                dim = (d.month != month)
                highlight = (d == today)
                grid.addWidget(
                    self.day_cell(
                        str(d.day),
                        dim=dim,
                        highlight=highlight,
                        week_current=is_current_week,
                        weekend=(c >= 5),
                    ),
                    r + 1,
                    c + 1,
                )

        layout.addWidget(grid_widget, 1)
        return month_panel

    def go_today(self):
        today = date.today()
        self.state.year = today.year
        self.state.month = today.month
        self.render()

    def reset_to_default(self):
        """Reset flyout to default state: current month."""
        today = date.today()
        self.state.year = today.year
        self.state.month = today.month
        self.render()

    def set_pinned(self, pinned: bool):
        self._pinned = pinned
        self._sync_pin_button()
        self._suppress_hide = True
        self._apply_window_flags()
        if self.isVisible():
            self.show()
            if pinned:
                self.raise_()
                self.activateWindow()
        QTimer.singleShot(220, self._clear_suppress_hide)

    def _clear_suppress_hide(self):
        self._suppress_hide = False

    def prev_month(self):
        y, m = self.state.year, self.state.month
        m -= 1
        if m < 1:
            m = 12
            y -= 1
        self.state.year, self.state.month = y, m
        self.render()

    def next_month(self):
        y, m = self.state.year, self.state.month
        m += 1
        if m > 12:
            m = 1
            y += 1
        self.state.year, self.state.month = y, m
        self.render()

    def toggle_months_view(self):
        self._months_count = 3 if self._months_count == 1 else 1
        self._save_months_count()
        self._update_view_button()
        self._update_window_size()
        self.render()

    def dow_cell(self, text: str, weekend: bool = False) -> QFrame:
        frame = QFrame()
        frame.setProperty("cellRole", "dow")
        lab = QLabel(text)
        lab.setObjectName("DowLabel")
        if weekend:
            lab.setProperty("weekend", "true")
        lab.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.addWidget(lab)
        return frame

    def week_cell(self, text: str, week_current: bool = False) -> QFrame:
        frame = QFrame()
        frame.setProperty("cellRole", "week")
        frame.setProperty("weekCurrent", "true" if week_current else "false")
        lab = QLabel(text)
        lab.setObjectName("WeekLabel")
        lab.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(lab)
        return frame

    def day_cell(
        self,
        text: str,
        dim: bool = False,
        highlight: bool = False,
        week_current: bool = False,
        weekend: bool = False,
    ) -> QFrame:
        frame = QFrame()
        frame.setProperty("cellRole", "day")
        frame.setProperty("weekCurrent", "true" if week_current else "false")
        state = "today" if highlight else ("dim" if dim else "normal")
        frame.setProperty("state", state)
        frame.setAttribute(Qt.WA_Hover, True)
        lab = QLabel(text)
        lab.setObjectName("DayLabel")
        if highlight:
            lab.setProperty("today", "true")
        if dim:
            lab.setProperty("dim", "true")
        if weekend:
            lab.setProperty("weekend", "true")
        lab.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(lab, 0, Qt.AlignCenter)
        return frame

    def render(self):
        self._sync_controls()
        self._set_info_text()
        self._clear_month_views()

        offsets = [0] if self._months_count == 1 else [-1, 0, 1]
        for offset in offsets:
            y, m = self._month_with_offset(self.state.year, self.state.month, offset)
            month_view = self._build_month_view(y, m)
            self.months_layout.addWidget(month_view, 1)
            self._month_views.append(month_view)


class WeekBadge(QWidget):
    # unchanged (your minimal padding is kept)
    def __init__(self, get_week_callable, on_left_click, context_menu, settings: QSettings):
        super().__init__()
        self.get_week = get_week_callable
        self.on_left_click = on_left_click
        self.ctx_menu = context_menu
        self.settings = settings

        self._dragging = False
        self._did_drag = False
        self._drag_offset = QPoint(0, 0)
        self._press_global = QPoint(0, 0)
        self._drag_threshold = 6

        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self._apply_style(QColor(0, 120, 212), QColor(255, 255, 255))

        self.update_text()

        if not self.restore_position():
            self.move_default()

        self.timer = QTimer(self)
        self.timer.setInterval(5 * 60 * 1000)
        self.timer.timeout.connect(self.update_text)
        self.timer.start()

    def _apply_style(self, bg: QColor, fg: QColor):
        self.label.setStyleSheet(f"""
            QLabel {{
                color: rgba({fg.red()},{fg.green()},{fg.blue()},255);
                font-family: "{FONT_FAMILY}", "Segoe UI";
                font-weight: 600;
                font-size: 16px;
                padding: 4px 8px;
                background: rgba({bg.red()},{bg.green()},{bg.blue()},235);
                border: 1px solid rgba(0,0,0,70);
                border-radius: 12px;
            }}
        """)

    def apply_theme(self, theme: Theme):
        bg = theme.accent
        fg = text_color_for_bg(bg)
        self._apply_style(bg, fg)

    def clamp_to_screen(self, pos: QPoint) -> QPoint:
        screen = QApplication.primaryScreen()
        if not screen:
            return pos
        geo = screen.availableGeometry()
        x = max(geo.left(), min(pos.x(), geo.right() - self.width()))
        y = max(geo.top(),  min(pos.y(), geo.bottom() - self.height()))
        return QPoint(x, y)

    def move_default(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        margin = 14
        self.adjustSize()
        x = geo.right() - self.width() - margin
        y = geo.bottom() - self.height() - margin
        self.move(QPoint(x, y))

    def save_position(self):
        p = self.pos()
        self.settings.setValue("badge/x", int(p.x()))
        self.settings.setValue("badge/y", int(p.y()))
        self.settings.sync()

    def restore_position(self) -> bool:
        x = self.settings.value("badge/x", None)
        y = self.settings.value("badge/y", None)
        if x is None or y is None:
            return False
        try:
            pos = QPoint(int(x), int(y))
        except Exception:
            return False
        self.adjustSize()
        self.move(self.clamp_to_screen(pos))
        return True

    def update_text(self):
        w = self.get_week()
        self.label.setText(f"W{w:02d}")
        self.label.adjustSize()
        self.adjustSize()
        self.move(self.clamp_to_screen(self.pos()))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._did_drag = False
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.RightButton:
            self.ctx_menu.show_at(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            current_global = event.globalPosition().toPoint()
            dist = (current_global - self._press_global).manhattanLength()
            if dist >= self._drag_threshold:
                self._did_drag = True
            if self._did_drag:
                new_top_left = current_global - self._drag_offset
                self.move(self.clamp_to_screen(new_top_left))
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            if self._did_drag:
                self.save_position()
            else:
                self.on_left_click()
            event.accept()


class InfoDialog(QDialog):
    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._update_status = "unknown"
        self._update_tag = None

        self.setWindowTitle("Info")
        # Transparent outer window so rounded shell corners don't show a square backdrop
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("InfoShell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(12, 12, 12, 12)
        shell_layout.setSpacing(8)
        root.addWidget(self.shell)

        banner = QLabel()
        banner.setObjectName("InfoBanner")
        banner.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        banner_pix = QPixmap(resource_path("branding", "weeknum_banner.png"))
        if banner_pix.isNull():
            banner.setText("WeekNum App")
            banner.setObjectName("InfoTitle")
        else:
            scale = 0.25
            target_w = max(1, int(banner_pix.width() * scale))
            target_h = max(1, int(banner_pix.height() * scale))
            banner.setPixmap(
                banner_pix.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            banner.setScaledContents(False)
            banner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        project = QLabel(
            'Project: <a href="https://github.com/pbuzdygan/weeknum">https://github.com/pbuzdygan/weeknum</a>'
        )
        project.setTextFormat(Qt.TextFormat.RichText)
        project.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        project.setOpenExternalLinks(True)

        author = QLabel("Author: Przemyslaw Buzdygan")

        github = QLabel(
            'GitHub: <a href="https://pbuzdygan.github.io">https://pbuzdygan.github.io</a>'
        )
        github.setTextFormat(Qt.TextFormat.RichText)
        github.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        github.setOpenExternalLinks(True)

        version = QLabel(f"Version: {APP_VERSION}")
        self.update_icon = QLabel("")
        self.update_icon.setFixedSize(14, 14)
        self.update_icon.setScaledContents(True)

        self.update_status = QLabel("")
        self.update_status.setTextFormat(Qt.TextFormat.RichText)
        self.update_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.update_status.setOpenExternalLinks(True)
        self.update_status.setObjectName("UpdateStatus")

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)
        shell_layout.addLayout(content_row)

        content_row.addWidget(banner, 0, Qt.AlignLeft)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        content_row.addLayout(text_col, 1)

        text_col.addStretch(1)
        text_col.addWidget(project, 0, Qt.AlignHCenter)
        text_col.addWidget(author, 0, Qt.AlignHCenter)
        text_col.addWidget(github, 0, Qt.AlignHCenter)
        text_col.addWidget(version, 0, Qt.AlignHCenter)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        status_row.addWidget(self.update_icon, 0, Qt.AlignVCenter)
        status_row.addWidget(self.update_status, 0, Qt.AlignVCenter)
        status_row.setAlignment(Qt.AlignHCenter)
        text_col.addLayout(status_row)
        text_col.addStretch(1)

        shell_layout.addSpacing(6)
        shell_layout.addWidget(close_btn, 0, Qt.AlignRight)

        # Keep window consistent with the calendar flyout (no extra shadow outside corners)
        self.shell.setGraphicsEffect(None)

        self.apply_theme(theme)

    def apply_theme(self, theme: Theme):
        self._theme = theme
        self.setStyleSheet(build_styles(theme)["info"])
        self._render_update_status()

    def set_update_status(self, status: str, tag: str | None):
        self._update_status = status
        self._update_tag = tag
        self._render_update_status()

    def _render_update_status(self):
        def make_status_icon(color: QColor, kind: str) -> QPixmap:
            size = 14
            pm = QPixmap(size, size)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(color, 2))
            if kind == "check":
                path = QPainterPath()
                path.moveTo(size * 0.2, size * 0.55)
                path.lineTo(size * 0.45, size * 0.78)
                path.lineTo(size * 0.82, size * 0.28)
                p.drawPath(path)
            elif kind == "arrow":
                path = QPainterPath()
                path.moveTo(size * 0.5, size * 0.2)
                path.lineTo(size * 0.5, size * 0.85)
                path.moveTo(size * 0.3, size * 0.38)
                path.lineTo(size * 0.5, size * 0.2)
                path.lineTo(size * 0.7, size * 0.38)
                p.drawPath(path)
            p.end()
            return pm

        if self._update_status == "update_available" and self._update_tag:
            label = (
                f'New version available: {self._update_tag} '
                f'(<a href="{UPDATE_LATEST_URL}">Download</a>)'
            )
            self.update_icon.setPixmap(make_status_icon(QColor(255, 149, 0), "arrow"))
        else:
            label = "Up to date"
            self.update_icon.setPixmap(make_status_icon(QColor(46, 160, 67), "check"))
        self.update_status.setText(label)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowDeactivate:
            self.hide()
        super().changeEvent(event)


class MenuItem(QWidget):
    def __init__(
        self,
        text: str,
        checkable: bool,
        checked: bool,
        on_click,
        check_color: QColor,
        parent=None
    ):
        super().__init__(parent)
        self.setObjectName("MenuItem")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._checkable = checkable
        self._on_click = on_click
        self._check_color = check_color
        if self._checkable:
            self.setProperty("checked", "true" if checked else "false")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.check_label = QLabel("")
        self.check_label.setObjectName("MenuCheck")
        self.check_label.setFixedWidth(14)
        self.check_label.setFixedHeight(14)
        self.check_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.text_label = QLabel(text)
        self.text_label.setObjectName("MenuText")
        self.text_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout.addWidget(self.check_label)
        layout.addWidget(self.text_label, 1)
        self.setChecked(checked)

    def setCheckColor(self, color: QColor):
        self._check_color = color
        if self._checkable and self.property("checked") == "true":
            self.check_label.setPixmap(make_checkmark_pixmap(self._check_color, 14))

    def setChecked(self, checked: bool):
        if self._checkable:
            if checked:
                self.check_label.setPixmap(make_checkmark_pixmap(self._check_color, 14))
            else:
                self.check_label.setPixmap(QPixmap())
            self.setProperty("checked", "true" if checked else "false")
            self.style().unpolish(self)
            self.style().polish(self)

    def setText(self, text: str):
        self.text_label.setText(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._on_click:
                self._on_click(self)
            event.accept()
        else:
            super().mousePressEvent(event)


class FluentMenu(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self._item_to_action = {}
        self._check_color = QColor(31, 31, 31)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        self.shell = QFrame(self)
        self.shell.setObjectName("MenuShell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(6, 6, 6, 6)
        shell_layout.setSpacing(4)
        root.addWidget(self.shell)

        self._layout = shell_layout

    def setStyleSheet(self, style: str):
        super().setStyleSheet(style)

    def add_action(self, action: QAction):
        item = MenuItem(
            action.text(),
            action.isCheckable(),
            action.isChecked(),
            self._on_item_clicked,
            check_color=self._check_color,
            parent=self.shell,
        )
        self._layout.addWidget(item)
        self._item_to_action[item] = action

        if action.isCheckable():
            action.toggled.connect(item.setChecked)
        action.changed.connect(lambda a=action, i=item: i.setText(a.text()))

    def add_separator(self):
        sep = QFrame(self.shell)
        sep.setObjectName("MenuSeparator")
        sep.setFixedHeight(1)
        self._layout.addWidget(sep)

    def _on_item_clicked(self, item: MenuItem):
        action = self._item_to_action.get(item)
        if not action:
            return
        action.trigger()
        self.hide()

    def apply_theme(self, theme: Theme):
        self._check_color = QColor(255, 255, 255) if theme.mode == "dark" else QColor(31, 31, 31)
        for item in self._item_to_action.keys():
            item.setCheckColor(self._check_color)

    def show_at(self, global_pos: QPoint):
        self.adjustSize()
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = min(max(geo.left(), global_pos.x()), geo.right() - self.width())
            y = min(max(geo.top(), global_pos.y()), geo.bottom() - self.height())
            self.move(QPoint(x, y))
        else:
            self.move(global_pos)
        self.show()
        self.raise_()
        self.activateWindow()


class TrayApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setFont(QFont(FONT_FAMILY))
        QToolTip.setFont(QFont(FONT_FAMILY))

        self.app_icon = QIcon(resource_path("icons", "WeekNum.ico"))
        if not self.app_icon.isNull():
            self.app.setWindowIcon(self.app_icon)

        QSettings.setDefaultFormat(QSettings.IniFormat)
        self.settings = QSettings(APP_ORG, APP_NAME)

        now = date.today()
        self.state = State(year=now.year, month=now.month)
        self.win: CalendarWindow | None = None
        self.info_dialog: InfoDialog | None = None

        self.theme = detect_theme()
        self.styles = build_styles(self.theme)
        self.app.setStyleSheet(self.styles["app"])

        self.tray = QSystemTrayIcon()
        fallback = self.app.style().standardIcon(QStyle.SP_MessageBoxInformation)
        self.tray.setIcon(self.app_icon if not self.app_icon.isNull() else fallback)

        self.menu = FluentMenu()
        self.menu.setStyleSheet(self.styles["menu"])
        self.menu.apply_theme(self.theme)

        self.open_action = QAction("Open calendar")
        self.open_action.triggered.connect(self.toggle_window)

        self.info_action = QAction("Info")
        self.info_action.triggered.connect(self.show_info)

        self.pin_action = QAction("Pin window")
        self.pin_action.setCheckable(True)
        self.pin_action.triggered.connect(self.toggle_pin_window)
        self._syncing_pin_from_window = False

        self.quit_action = QAction("Quit")
        self.quit_action.triggered.connect(self.quit)

        # widget toggle
        self.toggle_badge_action = QAction("Show widget")
        self.toggle_badge_action.setCheckable(True)
        show_badge = self.settings.value("badge/visible", True)
        show_badge = str(show_badge).lower() not in ("0", "false", "no")
        self.toggle_badge_action.setChecked(show_badge)
        self.toggle_badge_action.setText("Hide widget" if show_badge else "Show widget")
        self.toggle_badge_action.toggled.connect(self.set_badge_visible)

        # autostart toggle (Windows)
        self.autostart_action = QAction("Autostart")
        self.autostart_action.setCheckable(True)
        if sys.platform.startswith("win"):
            self.autostart_action.setChecked(get_windows_autostart_enabled())
            self.autostart_action.toggled.connect(self.toggle_autostart)
        else:
            self.autostart_action.setEnabled(False)

        self.menu.add_action(self.info_action)
        self.menu.add_action(self.open_action)
        self.menu.add_separator()
        self.menu.add_action(self.autostart_action)
        self.menu.add_action(self.toggle_badge_action)
        self.menu.add_action(self.pin_action)
        self.menu.add_separator()
        self.menu.add_action(self.quit_action)

        self.tray.activated.connect(self.on_tray_activated)

        self.badge = WeekBadge(
            get_week_callable=lambda: iso_week(date.today()),
            on_left_click=self.toggle_window,
            context_menu=self.menu,
            settings=self.settings
        )
        self.badge.setVisible(self.toggle_badge_action.isChecked())
        self.badge.apply_theme(self.theme)

        # Update tray now + periodically
        self.update_tray()

        self.timer = QTimer()
        self.timer.setInterval(5 * 60 * 1000)
        self.timer.timeout.connect(self.update_tray)
        self.timer.start()

        # Theme watcher: keep light/dark in sync with system
        self.theme_timer = QTimer()
        self.theme_timer.setInterval(2000)  # 2s; cheap (reads registry)
        self.theme_timer.timeout.connect(self.refresh_theme_if_changed)
        self.theme_timer.start()

        self.tray.show()

        # Update check: run once per launch, async, no retries on failure.
        self._update_checked = False
        self._update_message_pending = False
        self._update_url = UPDATE_LATEST_URL
        self._update_status = "unknown"
        self._update_tag = None
        self._nam = QNetworkAccessManager(self.app)
        self._update_reply: QNetworkReply | None = None
        self._update_timeout: QTimer | None = None
        self.tray.messageClicked.connect(self._on_tray_message_clicked)
        QTimer.singleShot(1500, self.check_updates_on_startup)

    def _on_tray_message_clicked(self):
        if self._update_message_pending and self._update_url:
            QDesktopServices.openUrl(QUrl(self._update_url))

    def check_updates_on_startup(self):
        if self._update_checked:
            return
        self._update_checked = True

        req = QNetworkRequest(QUrl(UPDATE_API_URL))
        req.setRawHeader(b"User-Agent", b"WeekNumApp")
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        req.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")

        reply = self._nam.get(req)
        self._update_reply = reply
        reply.finished.connect(self._on_update_reply_finished)

        timeout = QTimer(self.app)
        timeout.setSingleShot(True)
        timeout.timeout.connect(lambda r=reply: self._abort_update_reply(r))
        timeout.start(5000)
        self._update_timeout = timeout

    def _abort_update_reply(self, reply: QNetworkReply):
        try:
            if reply and reply.isRunning():
                reply.abort()
        except Exception:
            pass

    def _on_update_reply_finished(self):
        reply = self._update_reply
        self._update_reply = None
        if self._update_timeout:
            self._update_timeout.stop()
            self._update_timeout = None

        self._update_status = "up_to_date"

        if reply is None:
            return

        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return
            raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
        except Exception:
            return
        finally:
            reply.deleteLater()

        try:
            payload = json.loads(raw)
        except Exception:
            return

        tag = payload.get("tag_name") if isinstance(payload, dict) else None
        if not isinstance(tag, str) or not tag.strip():
            return

        remote = parse_semver(tag)
        local = parse_semver(APP_VERSION)
        if remote is None or local is None:
            self._update_status = "up_to_date"
            return

        if remote <= local:
            self._update_status = "up_to_date"
            return

        self._update_status = "update_available"
        self._update_tag = tag
        self._update_message_pending = True
        QTimer.singleShot(5500, self._clear_update_message_pending)
        self.tray.showMessage(
            "WeekNum",
            f"New version available: {tag}. Click to download.",
            QSystemTrayIcon.NoIcon,
            5000,
        )

    def _clear_update_message_pending(self):
        self._update_message_pending = False

    def ensure_window(self):
        if self.win is None:
            self.win = CalendarWindow(self.state, self.theme, on_pin_changed=self._on_window_pin_changed)
            # sync with pin state
            self.win.set_pinned(self.pin_action.isChecked())

    def _on_window_pin_changed(self, checked: bool):
        self._syncing_pin_from_window = True
        self.pin_action.setChecked(checked)
        self._syncing_pin_from_window = False
        self.pin_action.setText("Unpin window" if checked else "Pin window")

    def update_tray(self):
        w = iso_week(date.today())
        self.tray.setToolTip(f"Week {w:02d}")
        text_color = QColor(255, 255, 255) if self.theme.mode == "dark" else QColor(0, 0, 0)
        self.tray.setIcon(make_week_icon(w, text_color=text_color))

        if self.badge:
            self.badge.update_text()

    def refresh_theme_if_changed(self):
        new_theme = detect_theme()
        # compare only mode + accent rgb (ignore alpha drift)
        if (new_theme.mode != self.theme.mode or
            (new_theme.accent.red(), new_theme.accent.green(), new_theme.accent.blue()) !=
            (self.theme.accent.red(), self.theme.accent.green(), self.theme.accent.blue())):
            self.theme = new_theme
            self.styles = build_styles(self.theme)
            self.app.setStyleSheet(self.styles["app"])
            self.menu.setStyleSheet(self.styles["menu"])
            self.menu.apply_theme(self.theme)
            if self.win:
                self.win.apply_theme(self.theme)
            if self.info_dialog:
                self.info_dialog.apply_theme(self.theme)
            if self.badge:
                self.badge.apply_theme(self.theme)
            self.update_tray()

    def show_info(self):
        if self.info_dialog is None:
            self.info_dialog = InfoDialog(self.theme)
        else:
            self.info_dialog.apply_theme(self.theme)
        self.info_dialog.set_update_status(self._update_status, self._update_tag)
        self.info_dialog.show()
        self.info_dialog.raise_()
        self.info_dialog.activateWindow()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_window()
        elif reason == QSystemTrayIcon.Context:
            self.menu.show_at(QCursor.pos())

    def toggle_window(self):
        self.update_tray()
        self.ensure_window()
        if self.win.isVisible():
            self.win.hide()
        else:
            self.win.reset_to_default()
            self.show_calendar_window()

    def toggle_pin_window(self, checked: bool):
        self.pin_action.setText("Unpin window" if checked else "Pin window")
        if self._syncing_pin_from_window:
            return
        self.ensure_window()
        self.win.set_pinned(checked)
        if checked:
            self.show_calendar_window()
        else:
            self.win.hide()

    def show_calendar_window(self):
        self.position_window_near_tray()
        # small show trick reduces flicker when using Popup
        self.win.setWindowOpacity(0.0)
        self.win.show()
        self.win.setFocus(Qt.ActiveWindowFocusReason)
        self.win.activateWindow()
        self.win.raise_()
        QTimer.singleShot(0, self._restore_window_opacity)

    def _restore_window_opacity(self):
        if self.win and self.win.isVisible():
            self.win.setWindowOpacity(1.0)

    def position_window_near_tray(self):
        self.ensure_window()
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        self.win.adjustSize()
        w = self.win.width()
        h = self.win.height()
        margin = 8
        extra_offset = 24
        x = geo.right() - w - margin
        y = geo.bottom() - h - margin - extra_offset
        self.win.move(QPoint(x, y))

    def set_badge_visible(self, visible: bool):
        self.settings.setValue("badge/visible", bool(visible))
        self.settings.sync()
        if self.badge:
            self.badge.setVisible(visible)
        self.toggle_badge_action.setText("Hide widget" if visible else "Show widget")

    def toggle_autostart(self, enabled: bool):
        ok = set_windows_autostart_enabled(bool(enabled))
        if not ok:
            self.autostart_action.blockSignals(True)
            self.autostart_action.setChecked(not enabled)
            self.autostart_action.blockSignals(False)
            QTimer.singleShot(
                100,
                lambda: self.tray.showMessage(
                    "WeekNum",
                    "Failed to update autostart setting.",
                    QSystemTrayIcon.Warning,
                    3000,
                ),
            )
            return

        QTimer.singleShot(
            100,
            lambda: self.tray.showMessage(
                "WeekNum",
                "Autostart enabled." if enabled else "Autostart disabled.",
                QSystemTrayIcon.Information,
                2000,
            ),
        )

    def quit(self):
        if self.badge:
            self.badge.save_position()
            self.badge.hide()
        if self.win:
            self.win.hide()
        self.tray.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    TrayApp().run()
