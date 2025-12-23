import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRect, QPoint, QSettings, QEvent
from PySide6.QtGui import (
    QIcon, QAction, QKeyEvent, QPixmap, QPainter, QFont, QColor, QCursor
)
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGridLayout, QFrame, QDialog, QStyle, QStackedLayout,
    QToolTip, QSizePolicy
)

APP_ORG = "WeekNum"
APP_NAME = "WeekNumApp"
APP_VERSION = "1.1.0"

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
FONT_DAY_PX = 13       # Calendar days: 13px Regular
FONT_LABEL_PX = 11     # Labels: 11px Regular
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
        p.setPen(text_color if text_color is not None else QColor(0, 0, 0))
        p.drawText(target, Qt.AlignCenter, txt)

        p.end()
        return pm

    icon = QIcon()
    for s in (16, 20, 24, 28, 32, 40, 48, 64, 96, 128):
        icon.addPixmap(draw(s))
    return icon


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

    if theme.mode == "dark":
        shell_bg = "rgb(32,32,32)"
        border = "rgba(255,255,255,0.10)"
        text_primary = "#ffffff"
        text_secondary = "#ffffff"
        dim_text = "rgba(255,255,255,0.72)"
        hover = f"rgba({accent_rgb},0.18)"
        week_bg = f"rgba({accent_rgb},0.14)"
        press = f"rgba({accent_rgb},0.26)"
        today_bg = f"rgba({accent_rgb},0.28)"
        today_text = "#ffffff"
        menu_bg = "#202020"
        menu_border = "rgba(255,255,255,0.14)"
        menu_item_hover = f"rgba({accent_rgb},0.20)"
        sep = "rgba(255,255,255,0.10)"
    else:
        shell_bg = "rgb(255,255,255)"
        border = "rgba(0,0,0,0.08)"
        text_primary = "#1f1f1f"
        text_secondary = "#666666"
        dim_text = "rgba(0,0,0,0.40)"
        hover = f"rgba({accent_rgb},0.08)"
        week_bg = f"rgba({accent_rgb},0.07)"
        press = f"rgba({accent_rgb},0.14)"
        today_bg = f"rgba({accent_rgb},0.15)"
        today_text = f"rgb({accent_rgb})"
        menu_bg = "#f8f8f8"
        menu_border = "#d0d0d0"
        menu_item_hover = "#e8f2ff"
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

        QPushButton#MonthButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 4px 8px; font-size: {FONT_HEADER_PX}px; font-weight: 600; color: {text_primary};
            min-height: 32px; text-align: left;
        }}
        QPushButton#NavButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 6px 10px; font-size: {FONT_NAV_PX}px; min-width: 34px; min-height: 38px;
            color: {text_primary};
        }}
        QPushButton#TodayButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 6px 10px; font-size: {FONT_BODY_PX}px; font-weight: 400; min-height: 38px;
            color: {text_primary};
        }}
        QPushButton#PickerYearButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 4px 8px; font-size: {FONT_HEADER_PX}px; font-weight: 600; min-height: 32px;
            color: {text_primary};
        }}
        QPushButton#PickerNavButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 4px 10px; font-size: {FONT_NAV_PX}px; min-height: 32px;
            color: {text_primary};
        }}

        QPushButton#MonthButton:hover,
        QPushButton#NavButton:hover,
        QPushButton#TodayButton:hover,
        QPushButton#PickerYearButton:hover,
        QPushButton#PickerNavButton:hover {{ background: {hover}; }}

        QPushButton#MonthButton:pressed,
        QPushButton#NavButton:pressed,
        QPushButton#TodayButton:pressed,
        QPushButton#PickerYearButton:pressed,
        QPushButton#PickerNavButton:pressed {{ background: {press}; }}

        QPushButton[currentMonth="true"] {{ background: {press}; }}
        QPushButton[currentYear="true"] {{ background: {press}; }}

        QLabel#DowLabel {{ color: {text_secondary}; font-size: {FONT_LABEL_PX}px; font-weight: 400; }}
        QFrame[cellRole="day"] {{ background: transparent; border-radius: 8px; }}
        QFrame[cellRole="day"][weekCurrent="true"] {{ background: {week_bg}; }}
        QFrame[cellRole="day"]:hover {{ background: {hover}; }}
        QFrame[cellRole="day"][state="today"] {{ background: {today_bg}; }}

        QLabel#DayLabel {{ font-size: {FONT_DAY_PX}px; font-weight: 400; color: {text_primary}; }}
        QLabel#DayLabel[today="true"] {{ color: {today_text}; font-weight: 600; }}
        QLabel#DayLabel[dim="true"] {{ color: {dim_text}; }}

        QFrame[cellRole="week"] {{ background: transparent; border-radius: 6px; }}
        QFrame[cellRole="week"][weekCurrent="true"] {{ background: {week_bg}; }}
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
        }}
        #MenuItem:hover {{
            background: {menu_item_hover};
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
    def __init__(self, state: State, theme: Theme):
        super().__init__()
        self.state = state
        self._pinned = False
        self._suppress_hide = False
        self._theme = theme

        today = date.today()
        self._today_year = today.year
        self._today_month = today.month
        self._picker_year = self.state.year
        self._year_page_start = self._today_year - 4

        self.setWindowTitle("Calendar - week numbers")
        self.setFixedSize(420, 340)
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
        shell_layout.setContentsMargins(12, 12, 12, 12)
        shell_layout.setSpacing(8)
        root.addWidget(self.shell)

        top = QHBoxLayout()

        self.month_btn = QPushButton("")
        self.month_btn.setObjectName("MonthButton")
        self.month_btn.clicked.connect(self.toggle_picker)

        self.prev_btn = QPushButton("◀")
        self.next_btn = QPushButton("▶")
        self.prev_btn.setObjectName("NavButton")
        self.next_btn.setObjectName("NavButton")

        self.today_btn = QPushButton("Today")
        self.today_btn.setObjectName("TodayButton")
        self.today_btn.clicked.connect(self.go_today)

        top.addWidget(self.month_btn, 1)
        top.addSpacing(6)
        top.addWidget(self.prev_btn)
        top.addWidget(self.next_btn)
        top.addSpacing(6)
        top.addWidget(self.today_btn)
        shell_layout.addLayout(top)

        card = QFrame()
        card.setObjectName("CalendarCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 6, 6, 6)
        card_layout.setSpacing(2)

        stack_container = QWidget(card)
        self.content_stack = QStackedLayout(stack_container)

        calendar_view = QWidget(stack_container)
        calendar_layout = QVBoxLayout(calendar_view)
        calendar_layout.setContentsMargins(0, 0, 0, 0)
        calendar_layout.setSpacing(0)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(2)
        self.grid.setVerticalSpacing(2)
        for c in range(8):
            self.grid.setColumnStretch(c, 1)
        for r in range(7):
            self.grid.setRowStretch(r, 1)
        calendar_layout.addLayout(self.grid, 1)
        self.content_stack.addWidget(calendar_view)

        picker_view = QWidget(stack_container)
        picker_layout = QVBoxLayout(picker_view)
        picker_layout.setContentsMargins(0, 0, 0, 0)
        picker_layout.setSpacing(8)

        picker_top = QHBoxLayout()
        self.picker_prev_years_btn = QPushButton("◀")
        self.picker_next_years_btn = QPushButton("▶")
        self.picker_prev_years_btn.setObjectName("PickerNavButton")
        self.picker_next_years_btn.setObjectName("PickerNavButton")

        self.picker_year_btn = QPushButton(str(self._picker_year))
        self.picker_year_btn.setObjectName("PickerYearButton")
        self.picker_year_btn.clicked.connect(self.show_years_view)

        picker_top.addWidget(self.picker_prev_years_btn)
        picker_top.addSpacing(4)
        picker_top.addWidget(self.picker_year_btn)
        picker_top.addSpacing(4)
        picker_top.addWidget(self.picker_next_years_btn)
        picker_top.addStretch(1)
        picker_layout.addLayout(picker_top)

        picker_stack_container = QWidget(picker_view)
        self.picker_stack = QStackedLayout(picker_stack_container)

        months_widget = QWidget(picker_stack_container)
        months_layout = QGridLayout(months_widget)
        months_layout.setHorizontalSpacing(6)
        months_layout.setVerticalSpacing(6)
        self.picker_month_buttons = []
        for i, name in enumerate(ENG_MONTHS, start=1):
            btn = QPushButton(name)
            btn.setProperty("month", i)
            btn.clicked.connect(self.on_picker_month_clicked)
            self.picker_month_buttons.append(btn)
            r = (i - 1) // 3
            c = (i - 1) % 3
            months_layout.addWidget(btn, r, c)

        years_widget = QWidget(picker_stack_container)
        years_layout = QGridLayout(years_widget)
        years_layout.setHorizontalSpacing(6)
        years_layout.setVerticalSpacing(6)
        self.picker_years_grid = years_layout

        self.picker_stack.addWidget(months_widget)
        self.picker_stack.addWidget(years_widget)
        picker_layout.addWidget(picker_stack_container)

        self.content_stack.addWidget(picker_view)
        card_layout.addWidget(stack_container, 1)
        shell_layout.addWidget(card, 1)

        self.prev_btn.clicked.connect(self.prev_month)
        self.next_btn.clicked.connect(self.next_month)
        self.picker_prev_years_btn.clicked.connect(self.prev_years_page)
        self.picker_next_years_btn.clicked.connect(self.next_years_page)

        self.apply_theme(self._theme)
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

    def toggle_picker(self):
        if self.content_stack.currentIndex() == 1:
            self.show_calendar()
            return
        self._picker_year = self.state.year
        self.picker_year_btn.setText(str(self._picker_year))
        self._year_page_start = self._today_year - 4
        self.render_years()
        self.update_month_highlight()
        self.show_months_view()

    def show_calendar(self):
        self.content_stack.setCurrentIndex(0)

    def show_months_view(self):
        self.picker_stack.setCurrentIndex(0)
        self.content_stack.setCurrentIndex(1)
        self.picker_prev_years_btn.setVisible(False)
        self.picker_next_years_btn.setVisible(False)

    def show_years_view(self):
        self.picker_stack.setCurrentIndex(1)
        self.content_stack.setCurrentIndex(1)
        self.picker_prev_years_btn.setVisible(True)
        self.picker_next_years_btn.setVisible(True)

    def on_picker_month_clicked(self):
        btn = self.sender()
        if not isinstance(btn, QPushButton):
            return
        m = int(btn.property("month"))
        self.state.year = self._picker_year
        self.state.month = m
        self.render()
        self.show_calendar()

    def on_picker_year_clicked(self):
        btn = self.sender()
        if not isinstance(btn, QPushButton):
            return
        self._picker_year = int(btn.property("year"))
        self.picker_year_btn.setText(str(self._picker_year))
        self.update_month_highlight()
        self.show_months_view()

    def prev_years_page(self):
        self._year_page_start -= 9
        self.render_years()

    def next_years_page(self):
        self._year_page_start += 9
        self.render_years()

    def render_years(self):
        while self.picker_years_grid.count():
            item = self.picker_years_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for i in range(9):
            y = self._year_page_start + i
            btn = QPushButton(str(y))
            btn.setProperty("year", y)
            is_current = (y == self._today_year)
            btn.setProperty("currentYear", "true" if is_current else "false")
            btn.clicked.connect(self.on_picker_year_clicked)
            r = i // 3
            c = i % 3
            self.picker_years_grid.addWidget(btn, r, c)

    def update_month_highlight(self):
        for btn in self.picker_month_buttons:
            is_current = self._picker_year == self._today_year and int(btn.property("month")) == self._today_month
            btn.setProperty("currentMonth", "true" if is_current else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def go_today(self):
        today = date.today()
        self.state.year = today.year
        self.state.month = today.month
        self.render()

    def reset_to_calendar(self):
        self.show_calendar()

    def reset_to_default(self):
        """Reset flyout to default state: current month + calendar view."""
        today = date.today()
        self.state.year = today.year
        self.state.month = today.month
        self._picker_year = self.state.year
        self._today_year = today.year
        self._today_month = today.month
        self._year_page_start = self._today_year - 4
        self.content_stack.setCurrentIndex(0)
        self.picker_stack.setCurrentIndex(0)
        self.render()

    def set_pinned(self, pinned: bool):
        self._pinned = pinned
        self._suppress_hide = True
        self._apply_window_flags()
        if self.isVisible():
            self.show()
            if pinned:
                self.raise_()
                self.activateWindow()
        QTimer.singleShot(0, self._clear_suppress_hide)

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

    def clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def dow_cell(self, text: str) -> QFrame:
        frame = QFrame()
        lab = QLabel(text)
        lab.setObjectName("DowLabel")
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

    def day_cell(self, text: str, dim=False, highlight=False, week_current: bool = False) -> QFrame:
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
        lab.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(lab, 0, Qt.AlignCenter)
        return frame

    def render(self):
        self.clear_grid()

        y, m = self.state.year, self.state.month
        self.month_btn.setText(f"{ENG_MONTHS[m-1]} {y}")

        self.grid.addWidget(self.week_cell(""), 0, 0)
        for col, name in enumerate(DOW, start=1):
            self.grid.addWidget(self.dow_cell(name), 0, col)

        start = month_grid_start(y, m)
        today = date.today()
        current_week_start = start_of_iso_week(today)

        for r in range(6):
            week_start = start + timedelta(days=7 * r)
            wn = iso_week(week_start)
            is_current_week = (week_start == current_week_start)
            self.grid.addWidget(self.week_cell(f"W{wn:02d}", week_current=is_current_week), r + 1, 0)

            for c in range(7):
                d = week_start + timedelta(days=c)
                dim = (d.month != m)
                highlight = (d == today)
                self.grid.addWidget(self.day_cell(str(d.day), dim=dim, highlight=highlight, week_current=is_current_week), r + 1, c + 1)


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
            'GitHub: <a href="https://www.github.com/pbuzdygan">https://www.github.com/pbuzdygan</a>'
        )
        github.setTextFormat(Qt.TextFormat.RichText)
        github.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        github.setOpenExternalLinks(True)

        version = QLabel(f"Version: {APP_VERSION}")

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
        text_col.addStretch(1)

        shell_layout.addSpacing(6)
        shell_layout.addWidget(close_btn, 0, Qt.AlignRight)

        # Keep window consistent with the calendar flyout (no extra shadow outside corners)
        self.shell.setGraphicsEffect(None)

        self.apply_theme(theme)

    def apply_theme(self, theme: Theme):
        self._theme = theme
        self.setStyleSheet(build_styles(theme)["info"])

    def changeEvent(self, event):
        if event.type() == QEvent.WindowDeactivate:
            self.hide()
        super().changeEvent(event)


class MenuItem(QWidget):
    def __init__(self, text: str, checkable: bool, checked: bool, on_click, parent=None):
        super().__init__(parent)
        self.setObjectName("MenuItem")
        self.setAttribute(Qt.WA_Hover, True)
        self._checkable = checkable
        self._on_click = on_click
        if self._checkable:
            self.setProperty("checked", "true" if checked else "false")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.check_label = QLabel("✓" if checked and checkable else "")
        self.check_label.setObjectName("MenuCheck")
        self.check_label.setFixedWidth(14)

        self.text_label = QLabel(text)
        self.text_label.setObjectName("MenuText")

        layout.addWidget(self.check_label)
        layout.addWidget(self.text_label, 1)

    def setChecked(self, checked: bool):
        if self._checkable:
            self.check_label.setText("✓" if checked else "")
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

        self.open_action = QAction("Open calendar")
        self.open_action.triggered.connect(self.toggle_window)

        self.info_action = QAction("Info")
        self.info_action.triggered.connect(self.show_info)

        self.pin_action = QAction("Pin window")
        self.pin_action.setCheckable(True)
        self.pin_action.triggered.connect(self.toggle_pin_window)

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

        self.menu.add_action(self.toggle_badge_action)
        self.menu.add_action(self.autostart_action)
        self.menu.add_separator()
        self.menu.add_action(self.open_action)
        self.menu.add_action(self.info_action)
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

    def ensure_window(self):
        if self.win is None:
            self.win = CalendarWindow(self.state, self.theme)
            # sync with pin state
            self.win.set_pinned(self.pin_action.isChecked())

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
