# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SnipForge is a GUI-based text expansion tool for Linux. It's a single-file Python application (`snipforge.py`) that runs in the system tray and expands text snippets when trigger sequences are typed.

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

**Installation paths:**
- Application: `~/.local/share/snipforge/snipforge.py`
- Config/data: `~/.config/snipforge/`
- Backups: `~/.local/share/snipforge/backups/`
- Launcher: `~/.local/bin/snipforge`
- Desktop entry: `~/.local/share/applications/snipforge.desktop`
- Autostart: `~/.config/autostart/snipforge.desktop`
- Systemd service: `~/.config/systemd/user/snipforge.service`

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

**Single-file application with these key components:**

- `SnippetDialog` - Qt dialog for creating/editing snippets (legacy, kept for compatibility)
- `SnippetEditorWidget` - Embedded editor widget for creating/editing snippets within the main window
- `KeyboardListener` - Background thread using evdev to detect trigger sequences (Wayland-compatible)
- `MainWindow` - Main Qt window with QStackedWidget for switching between list view and editor view, system tray integration, and expansion logic

**Data flow:** Keyboard input -> buffer matching -> trigger detection -> content expansion (with variable/form processing) -> clipboard paste or character typing

**Configuration:** Snippets stored as JSON at `~/.config/snipforge/snippets.json`

**Platform specifics:** Uses `wl-copy` for Wayland clipboard image operations

## Snippet Variable Syntax

- `{{date}}`, `{{time}}`, `{{datetime}}` - Date/time insertion
- `{{clipboard}}` - Paste clipboard content
- `{{cursor}}` - Cursor position marker
- `{{fieldname}}` - Prompts for text input
- `{{fieldname=opt1|opt2|opt3}}` - Dropdown selection
- `{{calc:expression}}` - Dynamic calculation (e.g., `{{calc:price * quantity * 1.08}}`)

## Current Work

**Status:** Completed

**Last worked on:** Cross-platform Linux installer

**What was done (Feb 2026):**
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

**Next steps:** Windows 11 compatibility
- Add platform detection in snipforge.py
- Use pynput for keyboard on Windows (instead of evdev)
- Use pyperclip for clipboard on Windows (instead of wl-copy/wl-paste)
- Update installer for Windows (Startup folder instead of systemd)
- Test on Windows 11
