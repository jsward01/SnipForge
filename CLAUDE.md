# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SnipForge is a cross-platform GUI-based text expansion tool for Linux and Windows. It's a single-file Python application (`snipforge.py`) that runs in the system tray and expands text snippets when trigger sequences are typed.

## Installation

**Recommended: Use the installer**
```bash
cd Documents/Syncthing/SnipForge
python install.py install       # Interactive install
python install.py --yes install # Non-interactive (auto-yes)
python install.py uninstall     # Uninstall
python install.py update        # Update to latest version
python install.py status        # Check installation status
python install.py version       # Show version info
```

**Backup and Restore:**
```bash
python install.py backup        # Backup configuration
python install.py backup --list # List available backups
python install.py restore       # Restore from latest backup
python install.py restore file  # Restore from specific backup
```

**Import/Export Snippets:**
```bash
python install.py export              # Export snippets to JSON
python install.py export mysnips.json # Export to specific file
python install.py import file.json    # Import snippets (merge)
python install.py import file.json --replace  # Replace all snippets
```

**Other Options:**
```bash
python install.py deps          # Install dependencies only
python install.py -v install    # Verbose installation
```

**Self-Contained Installer:**
```bash
python build_installer.py       # Creates snipforge_installer.py
# Then distribute snipforge_installer.py - it contains everything
```

**Supported Linux distributions:**
| Family | Distros | Package Manager |
|--------|---------|-----------------|
| Arch | CachyOS, Manjaro, EndeavourOS, Garuda, Artix | pacman |
| Debian | Debian, Ubuntu, Pop!_OS, Linux Mint, LMDE, Elementary, Zorin | apt |
| Fedora | Fedora, RHEL, CentOS Stream, Rocky, Alma, Nobara | dnf |

**Installation paths (Linux):**
- Application: `~/.local/share/snipforge/snipforge.py`
- Config/data: `~/.config/snipforge/`
- Backups: `~/.local/share/snipforge/backups/`
- Launcher: `~/.local/bin/snipforge`
- Desktop entry: `~/.local/share/applications/snipforge.desktop`
- Autostart: `~/.config/autostart/snipforge.desktop`
- Systemd service: `~/.config/systemd/user/snipforge.service`

**Installation paths (Windows):**
- Application: `%LOCALAPPDATA%\SnipForge\snipforge.py`
- Config/data: `%APPDATA%\SnipForge\`
- Backups: `%LOCALAPPDATA%\SnipForge\backups\`
- Start Menu: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\SnipForge.lnk`
- Startup (auto-start): `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SnipForge.lnk`

**GitHub Repository:** https://github.com/jsward01/SnipForge

## Running the Application (Manual)

```bash
# Install dependencies (if not using installer)
pip install PyQt5 pynput pyperclip Pillow evdev

# For Wayland support, add yourself to the input group (then log out/in)
sudo usermod -aG input $USER

# Run the application
python snipforge.py
```

## Architecture

**Single-file cross-platform application with these key components:**

- `SnippetDialog` - Qt dialog for creating/editing snippets (legacy, kept for compatibility)
- `SnippetEditorWidget` - Embedded editor widget for creating/editing snippets within the main window
- `KeyboardListener` - Background thread for keyboard monitoring (evdev on Linux/Wayland, pynput on Windows/X11)
- `MainWindow` - Main Qt window with QStackedWidget for switching between list view and editor view, system tray integration, and expansion logic

**Data flow:** Keyboard input -> buffer matching -> trigger detection -> content expansion (with variable/form processing) -> clipboard paste or character typing

**Configuration paths:**
- Linux: `~/.config/snipforge/snippets.json`
- Windows: `%APPDATA%\SnipForge\snippets.json`

**Platform detection:** `IS_WINDOWS`, `IS_LINUX`, `IS_MACOS` flags at module level

**Platform-specific features:**
- Linux/Wayland: Uses evdev for keyboard input, ydotool for keystroke injection, wl-copy/wl-paste for clipboard
- Windows: Uses pynput for keyboard input and keystroke injection, win32clipboard for advanced clipboard operations

## Snippet Variable Syntax

- `{{date}}`, `{{time}}`, `{{datetime}}` - Date/time insertion
- `{{clipboard}}` - Paste clipboard content
- `{{cursor}}` - Cursor position marker
- `{{fieldname}}` - Prompts for text input
- `{{fieldname=opt1|opt2|opt3}}` - Dropdown selection
- `{{calc:expression}}` - Dynamic calculation (e.g., `{{calc:price * quantity * 1.08}}`)

## Current Work

**Status:** "Select Date" calendar confirmed matching the Linux version (dark and light
mode). A code review (prompted by an independent finding from a separate Claude Code
session exploring this same repo on another machine) turned up and fixed three more real
bugs — see below. Installed version is now `1.1.5`. Nothing else is actively
broken/in-flight.

**Code-review fixes (Aug 2026, same round):**
1. **Windows/Linux separation regression.** The date-picker (`{{name:date}}` field)
   popup calendar's week-number-hiding and weekday/weekend coloring (added earlier this
   round) had been applied unconditionally, but it replaced code that was explicitly
   `if IS_WINDOWS:`-gated — so it was silently changing Linux's calendar rendering too,
   violating [[feedback_snipforge_windows_separation]]. Re-gated behind `IS_WINDOWS`
   (`snipforge.py` ~line 1332).
2. **Clipboard-clobbering bug (confirmed independently by another Claude Code session's
   exploration of this repo, and cross-checked line-for-line against its report).**
   `paste_image()` and `paste_html()` (used for inline images, tables, and rich content
   during snippet expansion) both overwrite the system clipboard via
   `win32clipboard.EmptyClipboard()`/`wl-copy` to paste via Ctrl+V, but neither saved or
   restored the clipboard's prior contents. Any snippet containing an image, table, or
   rich content permanently destroyed whatever the user had copied before expanding it,
   with no warning. Fixed by adding `save_system_clipboard()` / `restore_system_clipboard()`
   helpers (~line 332, right after `press_ctrl_v()`) and wrapping both paste functions'
   bodies in `try/finally` so the snapshot is restored even on error paths. Windows
   restore is a full multi-format snapshot via `EnumClipboardFormats`; Linux/Wayland
   restore is text-only (best-effort — wl-clipboard has no practical "snapshot every
   format" API since each `wl-copy` invocation claims sole ownership of the selection).
3. **Same clipboard bug, one more spot: `type_text()`.** The other session's report also
   flagged a sequencing interaction: `type_content_with_embeds()` calls
   `type_text(before) -> paste_image() -> type_text(after)` for mixed text/image
   snippets, and `type_text()` had its *own* separate save/restore using raw
   `pyperclip.paste()`/`copy()` (text-only). Once fix #2 lands, `paste_image()` correctly
   restores the true clipboard before `type_text(after)` runs, which self-heals that
   specific sequencing case -- but `type_text()`'s pyperclip-only save/restore still had
   the identical root bug on its own: if the user's actual original clipboard held an
   image (not text) at the moment expansion started, `pyperclip.paste()` returns `''` for
   it, and `type_text()` would permanently discard it once restored. Fixed by switching
   `type_text()` to the same `save_system_clipboard()`/`restore_system_clipboard()`
   helpers (full-fidelity, not text-only), wrapped in `try/finally` (~line 10315).

**Last worked on (Aug 2026):** Continuation of the Windows bug-fix round below. The
"Select Date" dialog (`SnippetEditorWidget.show_calendar_dialog()`, opened via Dynamic
Commands > Select Date) went through many rounds of trying to reskin Qt's native
`QCalendarWidget` via stylesheets — it never fully worked, so it was replaced with a
**hand-drawn calendar grid** (plain `QPushButton`/`QLabel` widgets we paint ourselves,
no `QCalendarWidget` involved at all). All changes are in the repo copy
(`C:\Users\JSWARD\SnipForge\snipforge.py`) and deployed to the installed copy
(`C:\Users\JSWARD\AppData\Local\SnipForge\snipforge.py`, currently version `1.1.2`) via
`install.py update`. **Nothing has been committed to git yet** — uncommitted on the
`windows` branch, per instruction to only commit when asked.

**Why the rewrite happened:** Several QSS rounds tried to fix a persistent white
background behind the Mon–Fri weekday header labels (visible on-screen, not just in
screenshots — confirmed by direct user observation, not just captures) by targeting
`QHeaderView`, `QHeaderView::section` (including `background-image: none` to defeat a
suspected baked-in native gradient), and `QTableCornerButton::section` (a separate
corner-button widget that was the real source of an earlier, different white box behind
"Sun"). None of it fully worked — native/Fusion header chrome on Windows doesn't fully
yield to stylesheets. Rather than keep guessing at QSS selectors, `show_calendar_dialog`
now builds its own grid: a `QHBoxLayout` nav bar (`<`/`>` buttons + a clickable
month/year label), a `QHBoxLayout` weekday header of plain `QLabel`s, and a `QGridLayout`
of `QPushButton`s for the day cells, all colored directly in Python from
`self.is_light_theme` — no native calendar chrome left to fight, in either theme.

**Screenshot debugging gotcha (worth remembering):** Several screenshots the user sent
mid-session showed rainbow-colored numbers and white boxes that turned out to be
artifacts of Windows' Snipping Tool "Live Text" / Text Actions overlay (Win+Shift+S),
not the actual app rendering — proven by two screenshots of the *identical* dialog state
(no code change in between) looking completely different. **When a screenshot shows
implausible rendering (rainbow text, boxes with no plausible CSS source), ask the user
to check the live screen directly before chasing it as a code bug** — but don't assume
overlay-artifact just because it looks weird; in this same session a white-box report
was dismissed once as likely overlay and turned out to be a real bug after user
confirmed it live. Direct on-screen confirmation is the reliable tie-breaker.

Feature added on top of the rewrite: clicking the "August 2026" label opens a small
popup (`QComboBox` for month + `QSpinBox` for year, OK/Cancel) to jump long distances
without repeatedly clicking `<`/`>` — mirrors the "common feature" the user asked for,
similar to Qt's own native month-button/year-spinbox pattern.

**The other calendar site** — `SnippetFormDialog`'s `{{name:date}}` field popup
(`QDateEdit.calendarWidget()`, around line ~1275) — is still the old native
`QCalendarWidget` with light-only QSS. It was never reported as visually broken (its
fixed light styling happens to mostly survive native chrome), so it was **not**
rewritten this round. If it turns out to have the same header/corner-button issue,
apply the same hand-drawn-grid treatment there.

**What still needs to be done:**
- Nothing outstanding from this round — user confirmed the calendar "looks perfect."
- Whenever the user is ready, commit the accumulated changes on the `windows` branch
  (ask before committing, per standing instruction — [[feedback_snipforge_windows_separation]]).
- Consider whether `SnippetFormDialog`'s date-picker popup calendar (still native
  `QCalendarWidget`) should get the same custom-grid treatment for consistency, if it's
  ever reported as looking off.

**Previous work (Aug 2026, earlier in the same round):** Windows-specific crash and
rendering fixes, found while the user was doing hands-on Windows testing.

Fixes made, in order:
1. **Crash executing any snippet with a `{{Name:date}}` field.** Root cause:
   `date_edit.calendarWidget().setStyle(QStyleFactory.create('Fusion'))` — combining a
   per-widget custom `QStyle` with `setStyleSheet()` on the same widget makes Qt wrap it
   in an internal `QStyleSheetStyle` proxy whose C++-side ownership isn't tracked by
   Python's refcounting; it crashes (access violation) once the widget is torn down, not
   during use. Removed per-widget `setStyle()` calls entirely from both calendar sites.
2. **Settings > Appearance > Background section overlapping/unreadable rows.** The
   3-row block only overlapped when the dialog was squeezed toward its old 500px min
   height; natural height needed ~533-571px. Wrapped the Appearance tab content in a
   `QScrollArea` (so it can never compress/overlap again) and bumped
   `setMinimumSize(550, 500)` → `(550, 585)`.
3. **Calendar coloring/legibility + stray week-number column** (initial pass, later
   superseded for the "Select Date" dialog by the full rewrite above).
4. **Settings dialog not switching theme live** (dark→light needed a reopen to take
   effect). Regression from fix #2: the scroll area's background color was computed once
   at construction and never re-applied on live switch. Added
   `update_appearance_tab_theme()`, called both at construction and from the existing
   `update_dialog_theme()`.
5. **Main window losing its background-image watermark after a live theme switch**
   (fixed by full app restart). Added `self.parent_window.update()` at the end of
   `SettingsDialog.apply_settings()` to force a repaint once the modal dialog stops
   sitting on top of it. Deliberately did **not** add `QApplication.processEvents()`
   alongside it — that hung the app reentrantly in testing.
6. **Calendar looking completely different from the Linux version** (initial attempt: set
   Fusion as the app-wide base style, `if IS_WINDOWS:` gated, in `main()` right after
   `QApplication(sys.argv)` is constructed. This is still in place and is a reasonable
   app-wide default, but it did **not** fully fix `QCalendarWidget` specifically — see the
   rewrite above).

**Key gotchas learned this round (worth remembering for future PyQt work here):**
- Never call `widget.setStyle(customStyleObject)` on a widget that also has
  `setStyleSheet()` applied — crashes at teardown. `QApplication.setStyle()` once at
  startup is the safe equivalent.
- `QCalendarWidget` is a poor fit for heavy re-theming on Windows — its header sections
  and corner-button widget carry native style chrome that stylesheets can't fully strip.
  For any calendar/date UI that needs to look identical across platforms, prefer building
  it from plain widgets (`QPushButton`/`QLabel` in a `QGridLayout`) rather than fighting
  the native widget's QSS.
- `install.py update` compares the `__version__` string between the repo and installed
  copies — it silently no-ops ("already latest") if you forget to bump it after editing.
- In this shell environment, `install.py` needs `PYTHONUTF8=1` set or it crashes on a
  `UnicodeDecodeError`/`UnicodeEncodeError` reading files / printing unicode symbols
  (`ℹ`, `▶`, etc.) under the default cp1252 console codepage.
- SnipForge is a tray app — closing the window does **not** quit the process
  (`app.setQuitOnLastWindowClosed(False)`). Code changes only take effect after using
  **"Quit SnipForge" from the tray icon's right-click menu**, then relaunching. This was
  the cause of at least one "the fix didn't work" report that was actually just a stale
  running process.
- Custom `QPushButton` glyphs need plain ASCII-safe characters (`<`/`>`) — fancier
  unicode (e.g. `‹`/`›` angle quotes) rendered as invisible/missing glyphs in this
  environment's default UI font.
- Small fixed-size `QPushButton`s need explicit `padding: 0;` in their stylesheet, or the
  native style's default button padding can crush multi-character text (two-digit day
  numbers were rendering squeezed/illegible in ~38px-wide buttons until padding was
  zeroed and the buttons widened).

**Previous work (Feb 2026):** First-run tutorial implementation

**What was done (Feb 2026):**
- Added first-run tutorial wizard:
  - New `TutorialDialog` class - 4-step wizard to onboard new users
  - Step 1 (Welcome): Explains tray icon location and basic concept
  - Step 2 (Create): Guides user through creating a simple snippet (`:h` -> `Hello!`)
  - Step 3 (Test): Lets user test the snippet, auto-detects trigger and shows success
  - Step 4 (Complete): Shows tips for useful snippets and how to create more
  - Theme-aware styling (dark/light modes)
  - "Don't show this again" checkbox
  - Skip button to bypass tutorial
  - Auto-advances when snippet trigger is detected during test step
  - Snippet is actually created in the system and persists
  - Tutorial state saved in `tutorial_completed` setting
  - Shows on first run only, using 500ms delay after window init
  - Connected to `KeyboardListener.trigger_detected` signal for real-time detection

**Previous work (Feb 2026):**
- Improved `install.py` dependency handling for all Linux distros:
  - Handles broken apt repositories gracefully (continues despite `apt update` errors)
  - Checks if pip is installed before attempting pip fallback
  - Auto-installs pip if missing via system package manager or ensurepip
  - Installs packages one-by-one for better error recovery
  - Verifies dependencies after each installation step
  - Shows clear manual install instructions if all automated methods fail
  - Works for Arch, Debian, Fedora families and unknown distros (pip fallback)

- Updated `install.py` for full Windows support:
  - Platform-aware installation: detects Windows/Linux automatically
  - Windows-specific paths: `%LOCALAPPDATA%\SnipForge` for app, `%APPDATA%\SnipForge` for config
  - Creates Start Menu shortcut via PowerShell/WScript.Shell COM object
  - Creates Startup folder shortcut for auto-start on login (optional)
  - Uses `pythonw.exe` for windowless execution
  - Windows-specific uninstall: removes shortcuts and directories
  - Windows-specific status check: shows shortcuts and process status
  - Platform-aware dependency installation: pip-only on Windows
  - All existing Linux functionality preserved

- Previously added Windows compatibility to snipforge.py:
  - Platform detection: `IS_WINDOWS`, `IS_LINUX`, `IS_MACOS` flags
  - Cross-platform config paths: `get_config_dir()` and `get_data_dir()` helper functions
  - Updated `KeyboardListener` to use evdev on Linux, pynput on Windows
  - Updated clipboard handling: win32clipboard for images/HTML on Windows, wl-copy/wl-paste on Linux
  - Cross-platform keyboard simulation:
    - `get_keyboard_controller()` - lazy-initialized pynput keyboard Controller
    - `press_ctrl_v()` - cross-platform Ctrl+V paste
    - `ydotool_key()` and `run_ydotool()` - use pynput on Windows, ydotool on Linux
    - `LINUX_KEYCODE_TO_PYNPUT` mapping for keycode compatibility
  - Cross-platform single instance check: Named mutex on Windows, Unix abstract sockets on Linux
  - Dependencies: Added pywin32 requirement for Windows

**What still needs to be done:**
- Test on Windows 11

**Previous work (Feb 2026):**
- Created `install.py` - cross-platform Python installer with full feature set:
  - Auto-detects Linux distribution family (Arch, Debian, Fedora)
  - Installs system dependencies via appropriate package manager (pacman, apt, dnf)
  - Falls back to pip if system packages unavailable
  - Copies application and assets to proper locations
  - Creates systemd user service for auto-start
  - Creates desktop entry and autostart entry
  - Optionally adds user to `input` group for Wayland keyboard access
  - Colored terminal output with progress indicators
  - `--yes` flag for non-interactive/scripted installs
  - `-v/--verbose` flag for detailed output
  - `status` command to check installation state
  - `uninstall` command with option to preserve config/snippets
  - `update` command to update to latest version (with optional backup)
  - `version` command shows installed/source/GitHub versions
  - `backup` command creates timestamped tarball of config
  - `backup --list` shows available backups
  - `restore` command restores from backup
  - `export` command exports snippets to JSON
  - `import` command imports snippets (merge or replace modes)
  - `deps` command installs dependencies only
- Created `build_installer.py` - generates self-contained installer:
  - Bundles snipforge.py, install.py, and all assets into single file
  - Base64 encodes all files for embedding
  - Output: `snipforge_installer.py` (~4.8 MB) can be distributed standalone
- Set up GitHub repository at https://github.com/jsward01/SnipForge
  - Created v1.0.0 release
  - Version checking against GitHub releases API

**What was done (Jan 2026):**
- Fixed `{{clipboard}}` to support images:
  - Uses `wl-paste --list-types` to detect clipboard content type
  - If image (PNG/JPEG/GIF): saves to temp file and converts to `{{image:path}}` for inline pasting
  - If text: uses existing pyperclip behavior
  - Graceful fallback to text-only if detection fails
- Fixed form dialog for snippets with `{{calc:expression}}`:
  - Fixed calculation processing in form dialog's `on_insert()` method
  - Fixed window focus restoration after form dialog closes (saves mouse position before dialog, clicks to restore after)
  - Added Enter key support in form dialog text fields via `returnPressed` signal
  - Added auto-focus to first text field when form dialog opens via `showEvent`
  - Added real-time calculation preview - calc fields update as user types, with green styling when complete

**Previous work (Jan 2026):**
- Added Dynamic Calculations feature:
  - New "Calculation" button in Dynamic Commands menu (right side of editor)
  - Syntax: `{{calc:expression}}` - evaluates math expressions during expansion
  - Operators: `+`, `-`, `*`, `/`, `%`, `^`, parentheses
  - Functions: `round()`, `floor()`, `ceil()`, `abs()`, `min()`, `max()`, `pow()`, `sqrt()`
  - Can reference form field values by name (e.g., `{{calc:price * quantity}}`)
  - Results rounded to 2 decimal places (whole numbers show without decimals)
  - Shows in preview with orange `= expression` badge
  - `insert_calculation_dialog()` method with expression builder UI
  - `process_calculations()` method evaluates expressions safely using eval with restricted builtins
- Removed subscript and superscript buttons from formatting toolbar:
  - Simplified Row 2 of toolbar (now: Emoji, Find, Undo, Redo)
  - Removed `subscript_btn`, `superscript_btn` and separator
  - Cleaned up `btn_style_modifiers` and `update_theme()` references

**Previous work (Jan 2026):**
- Added `RichContentEdit` custom QTextEdit class:
  - Captures HTML content when pasting from rich sources (tables, formatted text)
  - Stores HTML in `rich_html` attribute for later use during expansion
  - Auto-continues bullet, numbered, and checkbox lists when pressing Enter
  - Ends list when pressing Enter on empty list line
- Added checkbox list feature to snippet editor:
  - New `☐` button in formatting toolbar (alongside bullet and numbered list buttons)
  - `insert_checkbox_list()` method inserts checkboxes at cursor or prefixes selected lines
  - Auto-continues with `☐ ` when pressing Enter after checkbox line
  - Works with both unchecked `☐` and checked `☑` characters
- Added bullet and numbered list auto-continuation:
  - Pressing Enter after `• item` inserts new line with `• `
  - Pressing Enter after `1. item` inserts new line with `2. `
  - Works with bullets (`•`, `-`, `*`) and any number prefix
  - Preserves leading whitespace/indentation
- Removed Table button from formatting toolbar:
  - Users can copy/paste tables directly from word processors instead
  - Rich HTML content is preserved and pastes correctly back into word processors
- Fixed `{{cursor}}` positioning with inline images:
  - Content is now split at `{{cursor}}` marker first, then each part processed
  - Images before cursor are pasted, then images after cursor
  - Cursor ends up at correct position between the parts
- Fixed inline image pasting for word processors (LibreOffice, OnlyOffice):
  - Added Escape keypress after image paste to deselect auto-selected image
  - Added End keypress to move cursor after the image
  - Changed from Ctrl+Shift+V to Ctrl+V (Ctrl+Shift+V opens "Paste Special" dialog)
  - Proper timing delays between clipboard operations

**Previous work (Jan 2026):**
- Fixed `{{cursor}}` variable functionality:
  - Now properly positions cursor at marker location after expansion
  - Types text before marker, then text after, then moves cursor back with arrow keys
- Fixed inline image insertion with `{{image:/path/to/file.png}}` syntax:
  - Insert Image toolbar button now inserts `{{image:path}}` at cursor position
  - During expansion, images are pasted inline at the marker position
  - Removed Enter keypress before paste that was causing images to go to new line
  - Added `image` to special variables so it doesn't trigger form dialog
- Removed Image Selector from bottom of editor page:
  - Removed `select_image_btn`, `clear_image_btn`, `image_label` UI elements
  - Removed `self.image_path` variable and related methods
  - Removed `select_image()` and `clear_image()` methods
  - Removed `image_path` from `get_snippet()` return data
  - Use toolbar Insert Image button instead (inserts at cursor position)
  - Legacy `image_path` in snippet data still supported for backwards compatibility
- Replaced "Frequently Used" with user-controlled "Favorites" section:
  - Right-click any emoji (including custom emojis) to add/remove from Favorites
  - Favorites section updates in-place without closing the picker dialog
  - Custom emojis can be favorited using "custom:name" format in favorites list
  - Custom emoji right-click menu now shows both "Add/Remove from Favorites" and "Delete"
  - Favorites persist in `~/.config/snipforge/emoji_favorites.json`
  - Removed automatic usage tracking
  - Favorites section shows at top with ⭐ icon
  - Removed methods: `load_emoji_usage()`, `save_emoji_usage()`, `get_frequently_used_emojis()`, `_show_custom_emoji_menu()`
  - Added methods: `load_emoji_favorites()`, `save_emoji_favorites()`
- Simplified emoji picker from ~3,900 emojis to ~400 curated popular ones:
  - Replaced Unicode emoji-test.txt download with hardcoded curated list
  - Removed `emoji` library dependency (no longer needed)
  - Removed skin tone selector (all emojis use default yellow)
  - Instant loading (no network requests, no file parsing)
  - Categories: Favorites, Smileys & Faces, Gestures & People, Animals & Nature, Food & Drink, Travel & Places, Activities, Objects, Symbols, Custom
  - Each emoji has search terms for easy discovery (e.g., "happy" finds 😀😃😄)
  - Removed config files no longer needed:
    - `emoji-test.txt` - No longer downloaded
    - `emoji_settings.json` - No longer used (skin tone removed)
    - `emoji_usage.json` - Replaced with emoji_favorites.json
  - Config files:
    - `emoji_favorites.json` - User's favorite emojis list
    - `custom_emojis.json` - Custom emoji metadata
  - Removed methods: `load_emoji_settings()`, `save_emoji_settings()`, `_apply_skin_tone()`

**Previous work (Jan 2026):**
- Implemented Slack-like emoji picker with full Unicode support:
  - Category tab bar with icon buttons, orange underline on selected tab
  - Search by emoji name/description (e.g., "grinning" finds 😀)
  - Custom emoji support:
    - "Add Custom Emoji" button opens upload dialog
    - Supports PNG/GIF/JPG files of any size (auto-resized to 128x128)
    - Insert as embedded image (24x24) or shortcode (:name:)
    - Right-click on custom emoji to delete
    - Stored in `~/.config/snipforge/custom_emojis/`
  - Theme-aware styling (dark/light modes)
  - Emoji database caching at MainWindow level (builds once on first use)
  - Methods: `load_emoji_usage()`, `save_emoji_usage()`, `load_custom_emojis()`, `save_custom_emojis()`, `get_frequently_used_emojis()`, `build_emoji_database()`
  - Methods in SnippetEditorWidget: `_insert_custom_emoji()`, `_show_custom_emoji_menu()`, `_show_add_custom_emoji_dialog()`

**Previous work (Jan 2026):**
- Added visible border around back button on Add/Edit screen:
  - Added `border: 1px solid` styling for both dark (#616161) and light (#9E9E9E) themes
  - Reduced border-radius from 6px to 4px for more rectangular look
  - Increased button size from 28x28 to 32x32 to accommodate border
  - Added border styling to hover and pressed states
- Fixed light mode text selection highlight contrast:
  - Changed selection-background-color from #FFE0B2 (light peach) to #E67E00 (darker orange)
  - Changed selection-color to #FFFFFF for proper contrast
  - Updated QTableWidget, QLineEdit, QTextEdit, QComboBox, QTreeWidget
  - Dark mode unchanged (#3D2814)
- Created `create_custom_spinbox()` helper method:
  - Circular orange buttons with transparent background
  - Uses app's accent color (#FF6B00) with hover fill effect
  - Editable QLineEdit value field with validation
  - Hand cursor on buttons for clickability indication
- Redesigned Insert Table dialog with visual grid selector:
  - 10x8 grid of hoverable cells
  - Cells highlight in orange on hover to show selection
  - Live "X x Y" size display at top
  - Click anywhere in highlighted area to insert table
  - Theme-aware styling (dark/light modes)
- Added "Custom size..." option for larger tables:
  - Styled as underlined orange link below grid
  - Opens sub-dialog with +/- spinboxes
  - Supports up to 50 columns x 100 rows

**Previous work (Jan 2026):**
- Fixed squished emoji buttons in Insert Emoji dialog:
  - Root cause: Qt stylesheet `#objectName` selectors only work on children, not on the widget itself
  - Moved `QPushButton#emojiBtn` styles into dialog stylesheet (parent) instead of per-button
  - Added explicit size constraints: `min-width/max-width` and `min-height/max-height` (40x40)
  - Added `setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)` to each emoji button
- Fixed squished back button in snippet editor:
  - Added `QPushButton#backBtn` styles to MainWindow's dark and light theme stylesheets
  - Overrides global QPushButton padding (8px 16px) that was squishing the 36x36 button
  - Uses `‹` (U+2039) chevron character with explicit font settings
- Fixed oversized Close button in emoji picker:
  - Added `max-width: 120px` constraint and centered with stretch layout

**Earlier work (Jan 2026):**
- Fixed transparent/glitching dialogs from Add/Edit menus:
  - Added `create_dialog()` helper method that parents dialogs to main window
  - Set `Qt.WA_TranslucentBackground` to False on all editor dialogs
  - Fixed dialogs: Insert Table, Find/Replace, Calendar, Preview, Emoji Picker
  - Added `get_text_input()` and `get_item_input()` helpers for styled QInputDialog
  - Fixed Dynamic Commands dialogs (Text Field, Dropdown, Toggle, etc.)
- Fixed back button in snippet editor:
  - Moved to top-left with chevron style (like browser back button)
  - Dark rounded square with white chevron
- Changed default background opacity from 50% to 25%
- Added `show_emoji_picker` method with:
  - Categorized emoji grid (Smileys, Gestures, Objects, Symbols, Nature)
  - Search/filter functionality
  - Theme-aware styling
- Fixed tooltip styling:
  - Added QToolTip styling to both dark and light themes
  - Dark background with white text for visibility in both modes

**Earlier work (Jan 2026):**
- Expanded text formatting toolbar with two rows:
  - Row 1: Bold, Italic, Underline, Strikethrough, Link, Image, Bullet list, Numbered list, Checkbox list
  - Row 2: Emoji picker, Find/Replace, Undo, Redo
  - All buttons theme-aware (dark/light mode)
- Changed Save button behavior:
  - Stays on edit page after saving (doesn't return to list)
  - Shows "✓ Saved!" notification that auto-hides after 2 seconds
  - New snippets become "editing" mode after first save
- Fixed Settings dialog theme switching:
  - Dialog now updates its own theme when user changes theme selection
  - Added `update_dialog_theme()` method
- Added emoji icon picker for snippets:
  - Click the icon button next to title to pick an emoji
  - Icons display in the snippet list with the trigger
  - Stored in `icon_emoji` field in snippet data
- Added Find and Replace dialog with case-sensitive option
- Added Table insert dialog (markdown-style tables)
- Added comprehensive emoji picker for content insertion

**Earlier work (Jan 2026):**
- Added text formatting toolbar to snippet editor:
  - Bold (B), Italic (I), Underline (U), and Hyperlink (🔗) buttons
  - Wraps selected text with format markers or inserts at cursor
  - Theme-aware styling (dark/light mode support)
- Fixed save button styling:
  - Added visible border around save button
  - Proper styling for both dark and light modes
- Fixed back button:
  - Changed to "←" arrow character with bold styling
  - Added light mode styling with appropriate colors
- Fixed Dynamic Commands buttons for light mode:
  - Added `cmd_btn_style_light` with readable colors
  - Buttons now properly themed with light gray background and blue text
- Added `update_theme()` method to SnippetEditorWidget:
  - Updates all button styles when theme changes
  - Called by MainWindow's `apply_theme()` method

**Earlier work:**
- Updated back button to chevron style
- Made SettingsDialog theme-aware for light mode
- Made settings auto-apply without Save button
- Fixed app icon display on Wayland/KDE (PNG format, StartupWMClass, setDesktopFileName)
- Added background watermark logo at 50% opacity
- Updated dark forge theme (black background, semi-transparent elements)
- Converted dialogs to in-window views using QStackedWidget
- Dark forge theme with orange (#FF6B00) and blue (#4A90D9) accents
- App starts minimized to system tray
- Custom app and tray icons

**Services:** Both `ydotoold` and `snipforge` auto-start on login via systemd user services

**Icon/Asset files (installed):**
- `~/.config/snipforge/app_icon.png` - Window/taskbar icon (PNG)
- `~/.config/snipforge/app_icon.ico` - Window/taskbar icon (ICO)
- `~/.config/snipforge/tray_icon.ico` - System tray icon
- `~/.config/snipforge/background.png` - Background watermark logo (dark mode)
- `~/.config/snipforge/background_light.png` - Background watermark logo (light mode)

**Source files (in project folder):**
- `snipforge.py` - Main application
- `install.py` - Cross-platform installer
- `build_installer.py` - Generates self-contained installer
- `CLAUDE.md` - Project documentation
- `SnipForge Icon.png` - App icon source
- `SnipForge App Icon.ico` - App icon (ICO format)
- `SnipForge-Tray Icon.ico` - Tray icon source
- `SnipForge Logo-black copy.png` - Dark mode background
- `SnipForge_Logo-white.png` - Light mode background

**Next steps:** Windows 11 testing
- ~~Add platform detection in snipforge.py~~ (Done)
- ~~Use pynput for keyboard on Windows (instead of evdev)~~ (Done)
- ~~Use pyperclip/win32clipboard for clipboard on Windows~~ (Done)
- ~~Update installer for Windows (Windows paths, Start Menu shortcut, Startup folder)~~ (Done)
- Test on Windows 11
