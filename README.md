# SnipForge

A text expansion tool for Linux and Windows. Type a trigger (like `:sig`) and it automatically expands to your saved content.

## Features

- **System tray app** - runs quietly in the background
- **Rich text support** - bold, italic, links, images, lists
- **Dynamic variables** - insert date, time, clipboard content, or prompt for input
- **Calculations** - `{{calc:price * quantity * 1.08}}` for dynamic math
- **Cross-platform** - works on Linux (X11/Wayland) and Windows

## Quick Start

### Linux

```bash
# Download and run the installer
git clone https://github.com/jsward01/SnipForge.git
cd SnipForge
python install.py install
```

**Important for Wayland users (Pop!_OS, Fedora, Ubuntu 22.04+, etc.):**

The installer adds you to the `input` group for keyboard access. You **must log out and back in** for this to take effect. Without this step, SnipForge cannot detect your typing.

```bash
# Verify you're in the input group after logging back in:
groups | grep input
```

### Windows

```bash
git clone https://github.com/jsward01/SnipForge.git
cd SnipForge
python install.py install
```

## Usage

1. Click the tray icon to open SnipForge
2. Click "Add Snippet" to create a new snippet
3. Enter a trigger (e.g., `:sig`) and the content to expand
4. Type your trigger anywhere - it expands automatically!

### Example Snippets

| Trigger | Content | Use Case |
|---------|---------|----------|
| `:email` | `yourname@example.com` | Quick email entry |
| `:addr` | Your full address | Forms and shipping |
| `:sig` | Email signature block | Professional emails |
| `:date` | `{{date}}` | Inserts today's date |
| `:shrug` | `¯\_(ツ)_/¯` | Express confusion |

### Dynamic Variables

- `{{date}}` - Current date
- `{{time}}` - Current time
- `{{datetime}}` - Date and time
- `{{clipboard}}` - Paste clipboard content
- `{{cursor}}` - Position cursor here after expansion
- `{{fieldname}}` - Prompt for text input
- `{{fieldname=opt1|opt2|opt3}}` - Dropdown selection
- `{{calc:expression}}` - Math calculation

## Troubleshooting

### Snippets not expanding (Linux/Wayland)

1. **Check if you're in the input group:**
   ```bash
   groups | grep input
   ```
   If "input" is not listed, run:
   ```bash
   sudo usermod -aG input $USER
   ```
   Then **log out and back in**.

2. **Check if ydotool daemon is running:**
   ```bash
   systemctl --user status ydotoold
   ```
   If not running:
   ```bash
   systemctl --user enable --now ydotoold
   ```

3. **Verify keyboard detection:**
   ```bash
   python3 -c "
   from evdev import InputDevice, ecodes, list_devices
   for p in list_devices():
       d = InputDevice(p)
       if ecodes.EV_KEY in d.capabilities():
           if ecodes.KEY_A in d.capabilities()[ecodes.EV_KEY]:
               print(f'Found: {d.name}')
   "
   ```
   If no keyboards are found, you're not in the input group or need to log out/in.

### Snippets not expanding (Windows)

1. Make sure SnipForge is running (check system tray)
2. Some applications with elevated privileges may block input detection
3. Try running SnipForge as administrator if issues persist

### App won't start / crashes

Check dependencies are installed:
```bash
# Linux
pip install PyQt5 pynput pyperclip Pillow evdev

# Windows
pip install PyQt5 pynput pyperclip Pillow pywin32
```

## Installer Commands

```bash
python install.py install      # Install SnipForge
python install.py uninstall    # Uninstall
python install.py status       # Check installation status
python install.py update       # Update to latest version
python install.py backup       # Backup your snippets
python install.py restore      # Restore from backup
python install.py export       # Export snippets to JSON
python install.py import FILE  # Import snippets from JSON
```

## Configuration Locations

| Platform | Config Path |
|----------|-------------|
| Linux | `~/.config/snipforge/` |
| Windows | `%APPDATA%\SnipForge\` |

## Requirements

- Python 3.8+
- PyQt5
- Linux: evdev, ydotool (for Wayland)
- Windows: pywin32

## License

MIT License - see LICENSE file for details.

## Contributing

Issues and pull requests welcome at [github.com/jsward01/SnipForge](https://github.com/jsward01/SnipForge)
