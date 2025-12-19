# WeekNum App

WeekNum App is a lightweight Windows 11 tray application that shows the
current ISO week number and provides a compact calendar with week numbers.
It also includes an optional floating widget on the desktop.

Author: Przemyslaw Buzdygan  
Version: 1.0.0

## Features

- tray icon with the week number (digits only)
- tray tooltip with the week number
- tray context menu (right-click)
- Info dialog with author and version
- compact calendar shown above the taskbar
- month/year picker inside the same window (no separate dialog)
- Today button
- Pin window option (always on top)
- optional floating widget that can be shown/hidden
- widget position is persisted

## Run from source

Requirements:
- Python 3.10+ (recommended)
- PySide6

Install dependencies:

```bash
pip install PySide6
```

Run:

```bash
python weeknum_app.py
```

## Build EXE (Windows)

The simplest option is PyInstaller.

Install:

```bash
pip install pyinstaller
```

Build:

```bash
pyinstaller --noconsole --onefile --name WeekNumApp --clean weeknum_app.py
```

The EXE will be located in the `dist` directory.

## Configuration and data

The app stores settings with QSettings (for example, widget position and
visibility). Data is saved under the user's profile.
