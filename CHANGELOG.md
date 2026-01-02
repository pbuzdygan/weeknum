# Changelog

## 1.3.0

New feature:
- Added an automatic update check (tray notification) on startup that informs users when a newer release is available, with a clear update status in the Info dialog (including a direct download link).

Minor UI changes
- improving light\dark mode
- improving spacing in entire UI
- fixing issues with tray week-number rendering

## 1.2.1

- Minor UI correction in month picker view, changing order in main menu

## 1.2.0

- UI improvements for months and years picking and checking
- UI new layout for month picker function - now including info about quarter of the year

## 1.1.1

- ADD: enhance Windows EXE build process with version metadata support

## 1.1.0

- WeekNum Autostart: toggle start with Windows from tray menu

## 1.0.1

- Info dialog: added banner and clickable links
- Packaging: bundle `branding/weeknum_banner.png` and `icons/WeekNum.ico` for PyInstaller onefile builds
- App icon: set window/tray icon from `icons/WeekNum.ico` (when available)

## 1.0.0

- initial release of WeekNum App
- tray icon with week number (digits only) and tooltip
- tray menu with Open calendar, Pin/Unpin window, Show/Hide widget
- Info dialog with author and version
- Windows 11 style calendar with week numbers
- built-in month/year picker in the same window
- Today button
- optional week number dragable widget
