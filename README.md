# WeekNum App for Windows

<p align="center">
  <img src="branding/weeknum_banner.png" alt="WeekNum Banner" width="25%">
</p>

**WeekNum** App is a lightweight Windows 11 tray application that shows the
current ISO week number and provides a compact calendar with week numbers.
It also includes an optional floating widget on the desktop.


## Features

- tray icon with the week number (digits only)
- tray tooltip with the week number
- tray context menu (right-click)
- Info dialog with banner, clickable links, author and version
- compact calendar shown above the taskbar
- month/year picker inside the same window (no separate dialog)
- Today button
- Pin window option (always on top)
- optional floating widget that can be shown/hidden
- floating, dragable widget
- **WeekNum Autostart** can be enabled/disabled from menu

---
## Demo / Screenshots

### Main UI
<p align="center">
  <img src="branding/0_dark.png" width="45%" alt="Main window Dark">
  <img src="branding/0_light.png" width="45%" alt="Main window Light">
</p>
<p align="center">
  <img src="branding/1_dark.png" width="45%" alt="Menu Dark">
  <img src="branding/1_light.png" width="45%" alt="Menu Light">
</p>

## Download ready app

App has been compiled (using method described in **Build Exe (Windows)**)
and is ready for You to download in repository's folder:

```bash
/latest_exe/
```

## Build EXE (Windows)

The simplest option is PyInstaller.

Install:

```bash
pip install pyinstaller
```
alternatively

```bash
python -m pip install pyinstaller
```

Build:

```bash
pyinstaller --noconsole --onefile --name WeekNumApp --clean --icon icons\WeekNum.ico --add-data "branding\weeknum_banner.png;branding" --add-data "icons\WeekNum.ico;icons" weeknum_app.py
```

The EXE will be located in the `dist` directory.

## Run from source

Requirements:
- Python 3.10+ (recommended)
- PySide6

Install dependencies:

for PySide6:

```bash
pip install PySide6
```
alternatively

```bash
python -m pip install PySide6
```
Run:

```bash
python weeknum_app.py
```

## Configuration and data

The app stores settings with QSettings (for example, widget position and
visibility). Data is saved under the user's profile.

## Buy Me a Coffee
If You like results of my efforts, feel free to show that by supporting me.

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/pbuzdygan)
<p align="left">
  <img src="branding/bmc_qr.png" width="25%" alt="BMC QR code">
</p>
