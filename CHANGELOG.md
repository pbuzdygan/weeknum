# Changelog

## 2.0.0
**Major Change Release**

- Major UI chnages:
  - Improved calendar readability by adding a `Wk` week column header, removing the `W` prefix from week numbers, and strengthening weekend and out-of-month day contrast.
  - Added a wider 3-month calendar view with visually separated month panels for better orientation.
  - Redesign the main calendar window layout to use a clearer direct header with month, year, Today, and 1M/3M controls.
  - Refined the calendar header and footer styling, including a cleaner bottom date line format: `Week XX · Friday, 10 April 2026`.
   - Added pin (`📌`) control directly in the main window header and synchronized it with tray menu pin/unpin state.

Security improvements:
- Hardened Windows release security:
  - added hash-locked `requirements-release-win.txt` for the release build
  - switched release dependency installation to `pip --require-hashes --only-binary=:all:`
  - added `SHA256SUMS` publication to GitHub Release assets
  - added GitHub artifact provenance attestation for release artifacts
  - added a separate GitHub Actions dependency audit workflow using `pip-audit`
- Updated release workflow actions to Node 24-ready versions and enabled `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`.
- Replaced JS release upload action with `gh release upload` to avoid Node runtime deprecation warnings.
- Pinned `PyInstaller` to `6.19.0` and enabled `pip` dependency caching in CI to speed up Windows build runs.
- Pinned application/build dependencies in `requirements.txt` (`PySide6`, `PyInstaller`) for reproducible builds.

Bug fixes:
- Fixed pin/unpin behavior to avoid unintended flyout hide caused by popup/tool flag switching during pin state changes.
- Fixed unpinned calendar flyout behavior to hide correctly on outside click (restored popup-style dismiss behavior), preventing the double-click tray toggle issue.

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
