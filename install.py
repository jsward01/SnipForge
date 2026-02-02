#!/usr/bin/env python3
"""
SnipForge Installer
Cross-platform installer for Linux and Windows.

Supported platforms:
- Windows 10/11
- Arch-based Linux (CachyOS, Manjaro, EndeavourOS, etc.)
- Debian-based Linux (Debian, Ubuntu, Pop!_OS, Linux Mint, LMDE, etc.)
- Fedora-based Linux (Fedora, RHEL, CentOS Stream, etc.)

Usage:
    python install.py install    # Install SnipForge
    python install.py uninstall  # Uninstall SnipForge
    python install.py status     # Check installation status
"""

import os
import sys
import shutil
import subprocess
import argparse
import json
import re
import tarfile
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

# Platform detection
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform.startswith('linux')
IS_MACOS = sys.platform == 'darwin'


# ============================================================================
# Configuration
# ============================================================================

APP_NAME = "snipforge"
APP_DISPLAY_NAME = "SnipForge"
APP_DESCRIPTION = "Forge your snippets - Quick text expansion tool"
APP_VERSION = "1.0.0"
GITHUB_REPO = "jsward01/SnipForge"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Global flags (set by argument parser)
AUTO_YES = False   # --yes flag for non-interactive mode
VERBOSE = False    # --verbose flag for detailed output

# Installation paths (platform-specific)
if IS_WINDOWS:
    # Windows paths
    APPDATA = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
    LOCALAPPDATA = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    INSTALL_DIR = LOCALAPPDATA / APP_DISPLAY_NAME
    CONFIG_DIR = APPDATA / APP_DISPLAY_NAME
    BACKUP_DIR = INSTALL_DIR / "backups"
    # Start Menu and Startup locations
    START_MENU = APPDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    STARTUP_FOLDER = APPDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    START_MENU_SHORTCUT = START_MENU / f"{APP_DISPLAY_NAME}.lnk"
    STARTUP_SHORTCUT = STARTUP_FOLDER / f"{APP_DISPLAY_NAME}.lnk"
    BIN_LINK = None  # Not used on Windows
    # Linux-specific paths (not used on Windows)
    DESKTOP_FILE = None
    AUTOSTART_FILE = None
    SYSTEMD_SERVICE = None
else:
    # Linux paths
    INSTALL_DIR = Path.home() / ".local" / "share" / APP_NAME
    CONFIG_DIR = Path.home() / ".config" / APP_NAME
    BACKUP_DIR = INSTALL_DIR / "backups"
    DESKTOP_FILE = Path.home() / ".local" / "share" / "applications" / f"{APP_NAME}.desktop"
    AUTOSTART_FILE = Path.home() / ".config" / "autostart" / f"{APP_NAME}.desktop"
    SYSTEMD_SERVICE = Path.home() / ".config" / "systemd" / "user" / f"{APP_NAME}.service"
    BIN_LINK = Path.home() / ".local" / "bin" / APP_NAME
    # Windows-specific paths (not used on Linux)
    START_MENU_SHORTCUT = None
    STARTUP_SHORTCUT = None

# Source files (relative to installer location)
SCRIPT_DIR = Path(__file__).parent.resolve()
SOURCE_FILES = {
    "main": SCRIPT_DIR / "snipforge.py",
    "icon_png": SCRIPT_DIR / "SnipForge Icon.png",
    "icon_ico": SCRIPT_DIR / "SnipForge App Icon.ico",
    "tray_ico": SCRIPT_DIR / "SnipForge-Tray Icon.ico",
    "logo_dark": SCRIPT_DIR / "SnipForge Logo-black copy.png",
    "logo_light": SCRIPT_DIR / "SnipForge_Logo-white.png",
}

# Colors for terminal output
class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


# ============================================================================
# Utility Functions
# ============================================================================

def print_header(text):
    """Print a formatted header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.RESET}\n")


def print_step(text):
    """Print a step indicator."""
    print(f"{Colors.BLUE}▶{Colors.RESET} {text}")


def print_success(text):
    """Print a success message."""
    print(f"{Colors.GREEN}✓{Colors.RESET} {text}")


def print_warning(text):
    """Print a warning message."""
    print(f"{Colors.YELLOW}⚠{Colors.RESET} {text}")


def print_error(text):
    """Print an error message."""
    print(f"{Colors.RED}✗{Colors.RESET} {text}")


def print_info(text):
    """Print an info message."""
    print(f"{Colors.CYAN}ℹ{Colors.RESET} {text}")


def print_verbose(text):
    """Print a message only in verbose mode."""
    global VERBOSE
    if VERBOSE:
        print(f"{Colors.MAGENTA}  →{Colors.RESET} {text}")


def prompt_yes_no(prompt, default=True):
    """
    Prompt user for yes/no input.
    Returns True for yes, False for no.
    Respects AUTO_YES flag and non-interactive terminals.
    """
    global AUTO_YES

    # In auto mode, return default
    if AUTO_YES:
        print_info(f"{prompt} [auto: {'yes' if default else 'no'}]")
        return default

    # If not a tty, use default
    if not sys.stdin.isatty():
        print_info(f"{prompt} [non-interactive: {'yes' if default else 'no'}]")
        return default

    # Interactive prompt
    hint = "[Y/n]" if default else "[y/N]"
    try:
        response = input(f"\n{Colors.YELLOW}{prompt} {hint}: {Colors.RESET}").strip().lower()
        if not response:
            return default
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return default


def run_command(cmd, check=True, capture=True, sudo=False):
    """Run a shell command."""
    if sudo:
        cmd = ["sudo"] + cmd

    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        if capture:
            print_error(f"Command failed: {' '.join(cmd)}")
            if e.stderr:
                print(f"    {e.stderr.strip()}")
        raise
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        raise


def command_exists(cmd):
    """Check if a command exists."""
    return shutil.which(cmd) is not None


# ============================================================================
# Distro Detection
# ============================================================================

class Distro:
    """Linux distribution information."""

    FAMILY_ARCH = "arch"
    FAMILY_DEBIAN = "debian"
    FAMILY_FEDORA = "fedora"
    FAMILY_UNKNOWN = "unknown"

    def __init__(self):
        self.id = "unknown"
        self.name = "Unknown Linux"
        self.family = self.FAMILY_UNKNOWN
        self.version = ""
        self.detect()

    def detect(self):
        """Detect the current Linux distribution."""
        os_release = Path("/etc/os-release")

        if not os_release.exists():
            return

        info = {}
        with open(os_release) as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    key, value = line.split("=", 1)
                    info[key] = value.strip('"')

        self.id = info.get("ID", "unknown").lower()
        self.name = info.get("PRETTY_NAME", info.get("NAME", "Unknown Linux"))
        self.version = info.get("VERSION_ID", "")

        # Determine family
        id_like = info.get("ID_LIKE", "").lower().split()

        if self.id in ["arch", "cachyos", "manjaro", "endeavouros", "garuda", "artix"]:
            self.family = self.FAMILY_ARCH
        elif self.id in ["arch"] or "arch" in id_like:
            self.family = self.FAMILY_ARCH
        elif self.id in ["debian", "ubuntu", "pop", "linuxmint", "lmde", "elementary", "zorin", "kali"]:
            self.family = self.FAMILY_DEBIAN
        elif self.id in ["debian", "ubuntu"] or "debian" in id_like or "ubuntu" in id_like:
            self.family = self.FAMILY_DEBIAN
        elif self.id in ["fedora", "rhel", "centos", "rocky", "alma", "nobara"]:
            self.family = self.FAMILY_FEDORA
        elif "fedora" in id_like or "rhel" in id_like:
            self.family = self.FAMILY_FEDORA

    def __str__(self):
        return f"{self.name} ({self.family})"


# ============================================================================
# Dependency Management
# ============================================================================

class DependencyManager:
    """Manages system and Python dependencies."""

    # System package names per distro family
    SYSTEM_PACKAGES = {
        Distro.FAMILY_ARCH: [
            "python-pyqt5",
            "python-pynput",
            "python-pyperclip",
            "python-pillow",
            "python-evdev",
            "wl-clipboard",  # For Wayland clipboard support
            "xdotool",       # For X11 fallback
        ],
        Distro.FAMILY_DEBIAN: [
            "python3-pyqt5",
            "python3-pynput",
            "python3-pyperclip",
            "python3-pil",
            "python3-evdev",
            "wl-clipboard",
            "xdotool",
        ],
        Distro.FAMILY_FEDORA: [
            "python3-qt5",
            "python3-pynput",
            "python3-pyperclip",
            "python3-pillow",
            "python3-evdev",
            "wl-clipboard",
            "xdotool",
        ],
    }

    # Fallback pip packages if system packages unavailable
    PIP_PACKAGES_LINUX = [
        "PyQt5",
        "pynput",
        "pyperclip",
        "Pillow",
        "evdev",
    ]

    # Windows pip packages
    PIP_PACKAGES_WINDOWS = [
        "PyQt5",
        "pynput",
        "pyperclip",
        "Pillow",
        "pywin32",
    ]

    def __init__(self, distro):
        self.distro = distro
        self.pip_packages = self.PIP_PACKAGES_WINDOWS if IS_WINDOWS else self.PIP_PACKAGES_LINUX

    def get_package_manager(self):
        """Get the package manager command for this distro."""
        if self.distro.family == Distro.FAMILY_ARCH:
            return "pacman"
        elif self.distro.family == Distro.FAMILY_DEBIAN:
            return "apt"
        elif self.distro.family == Distro.FAMILY_FEDORA:
            return "dnf"
        return None

    def install_system_packages(self):
        """Install system packages using the appropriate package manager."""
        pkg_manager = self.get_package_manager()
        packages = self.SYSTEM_PACKAGES.get(self.distro.family, [])

        if not pkg_manager or not packages:
            print_warning(f"No system packages defined for {self.distro.name}")
            return self.install_pip_packages()

        print_step(f"Installing system packages via {pkg_manager}...")

        try:
            if pkg_manager == "pacman":
                # Check which packages are not installed
                missing = []
                for pkg in packages:
                    result = run_command(["pacman", "-Qi", pkg], check=False)
                    if result.returncode != 0:
                        missing.append(pkg)

                if missing:
                    run_command(["pacman", "-S", "--noconfirm", "--needed"] + missing, sudo=True, capture=False)
                else:
                    print_info("All system packages already installed")

            elif pkg_manager == "apt":
                # Try apt update, but continue even if it fails (broken repos)
                print_verbose("Running apt update...")
                update_result = run_command(["apt", "update"], sudo=True, check=False, capture=True)
                if update_result.returncode != 0:
                    print_warning("apt update had errors (possibly broken repositories)")
                    print_info("Attempting to install packages anyway...")

                # Try to install packages one by one for better error handling
                failed_packages = []
                for pkg in packages:
                    try:
                        result = run_command(["apt", "install", "-y", pkg], sudo=True, capture=True, check=False)
                        if result.returncode == 0:
                            print_verbose(f"Installed {pkg}")
                        else:
                            print_verbose(f"Failed to install {pkg}")
                            failed_packages.append(pkg)
                    except Exception as e:
                        print_verbose(f"Error installing {pkg}: {e}")
                        failed_packages.append(pkg)

                if failed_packages:
                    print_warning(f"Some packages failed to install: {', '.join(failed_packages)}")
                    print_info("Will try pip for Python packages...")
                    # Don't return False yet - check if core Python deps are missing

            elif pkg_manager == "dnf":
                run_command(["dnf", "install", "-y"] + packages, sudo=True, capture=False)

            # Verify what we have after system package installation
            still_missing = self.check_dependencies()
            if still_missing:
                print_warning(f"Still missing after system install: {', '.join(still_missing)}")
                print_info("Falling back to pip for remaining packages...")
                return self.install_pip_packages()

            print_success("System packages installed")
            return True

        except subprocess.CalledProcessError as e:
            print_error(f"Failed to install system packages")
            print_info("Falling back to pip installation...")
            return self.install_pip_packages()

    def ensure_pip_installed(self):
        """Ensure pip is installed, install it if missing."""
        # Check if pip is available
        result = run_command([sys.executable, "-m", "pip", "--version"], check=False, capture=True)
        if result.returncode == 0:
            print_verbose("pip is already installed")
            return True

        print_warning("pip is not installed")
        print_step("Attempting to install pip...")

        # Try to install pip via system package manager first
        if self.distro.family == Distro.FAMILY_DEBIAN:
            try:
                run_command(["apt", "install", "-y", "python3-pip"], sudo=True, capture=False)
                # Verify pip works now
                result = run_command([sys.executable, "-m", "pip", "--version"], check=False, capture=True)
                if result.returncode == 0:
                    print_success("pip installed via apt")
                    return True
            except Exception:
                pass

        elif self.distro.family == Distro.FAMILY_ARCH:
            try:
                run_command(["pacman", "-S", "--noconfirm", "python-pip"], sudo=True, capture=False)
                result = run_command([sys.executable, "-m", "pip", "--version"], check=False, capture=True)
                if result.returncode == 0:
                    print_success("pip installed via pacman")
                    return True
            except Exception:
                pass

        elif self.distro.family == Distro.FAMILY_FEDORA:
            try:
                run_command(["dnf", "install", "-y", "python3-pip"], sudo=True, capture=False)
                result = run_command([sys.executable, "-m", "pip", "--version"], check=False, capture=True)
                if result.returncode == 0:
                    print_success("pip installed via dnf")
                    return True
            except Exception:
                pass

        # Try ensurepip as fallback
        print_info("Trying ensurepip...")
        try:
            run_command([sys.executable, "-m", "ensurepip", "--user"], check=False, capture=False)
            result = run_command([sys.executable, "-m", "pip", "--version"], check=False, capture=True)
            if result.returncode == 0:
                print_success("pip installed via ensurepip")
                return True
        except Exception:
            pass

        print_error("Could not install pip")
        print_info("Please install pip manually:")
        if self.distro.family == Distro.FAMILY_DEBIAN:
            print("    sudo apt install python3-pip")
        elif self.distro.family == Distro.FAMILY_ARCH:
            print("    sudo pacman -S python-pip")
        elif self.distro.family == Distro.FAMILY_FEDORA:
            print("    sudo dnf install python3-pip")
        else:
            print("    python3 -m ensurepip --user")
        return False

    def install_pip_packages(self):
        """Install packages via pip."""
        print_step("Installing Python packages via pip...")

        # First ensure pip is installed
        if not self.ensure_pip_installed():
            print_error("Cannot install pip packages without pip")
            return False

        # Install packages one by one for better error handling
        failed = []
        for pkg in self.pip_packages:
            try:
                result = run_command([
                    sys.executable, "-m", "pip", "install", "--user", "--upgrade", pkg
                ], capture=True, check=False)
                if result.returncode == 0:
                    print_verbose(f"Installed {pkg}")
                else:
                    print_verbose(f"Failed to install {pkg}")
                    failed.append(pkg)
            except Exception as e:
                print_verbose(f"Error installing {pkg}: {e}")
                failed.append(pkg)

        if failed:
            print_warning(f"Some packages failed to install: {', '.join(failed)}")

        # Check if the essential packages are now available
        still_missing = self.check_dependencies()
        if still_missing:
            print_error(f"Failed to install required packages: {', '.join(still_missing)}")
            print_info("You can try installing them manually:")
            print(f"    pip install {' '.join(still_missing)}")
            return False

        print_success("Python packages installed via pip")
        return True

    def check_dependencies(self):
        """Check if all required Python modules are available."""
        missing = []
        if IS_WINDOWS:
            modules = ["PyQt5", "pynput", "pyperclip", "PIL"]
            # Check for pywin32
            try:
                import win32api
            except ImportError:
                missing.append("pywin32")
        else:
            modules = ["PyQt5", "pynput", "pyperclip", "PIL", "evdev"]

        for module in modules:
            try:
                __import__(module if module != "PIL" else "PIL")
            except ImportError:
                missing.append(module)

        return missing


# ============================================================================
# Windows Shortcut Creation
# ============================================================================

def create_windows_shortcut(shortcut_path, target_path, working_dir=None, icon_path=None, description=None):
    """
    Create a Windows shortcut (.lnk file) using PowerShell.
    This avoids requiring pywin32 for shortcut creation.
    """
    if not IS_WINDOWS:
        return False

    # PowerShell script to create shortcut
    ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{target_path}"
'''
    if working_dir:
        ps_script += f'$Shortcut.WorkingDirectory = "{working_dir}"\n'
    if icon_path:
        ps_script += f'$Shortcut.IconLocation = "{icon_path}"\n'
    if description:
        ps_script += f'$Shortcut.Description = "{description}"\n'

    ps_script += '$Shortcut.Save()'

    try:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        print_verbose(f"PowerShell shortcut creation failed: {e}")
        return False


# ============================================================================
# Installation Functions
# ============================================================================

def check_source_files():
    """Verify that required source files exist."""
    print_step("Checking source files...")

    missing = []
    for name, path in SOURCE_FILES.items():
        if not path.exists():
            missing.append(f"{name}: {path}")

    if missing:
        print_error("Missing required files:")
        for f in missing:
            print(f"    - {f}")
        return False

    print_success("All source files found")
    return True


def create_directories_windows():
    """Create necessary directories on Windows."""
    print_step("Creating directories...")

    directories = [
        INSTALL_DIR,
        CONFIG_DIR,
        START_MENU,
        STARTUP_FOLDER,
    ]

    for dir_path in directories:
        if dir_path:
            created = not dir_path.exists()
            dir_path.mkdir(parents=True, exist_ok=True)
            if created:
                print_verbose(f"Created {dir_path}")

    print_success("Directories created")


def create_directories_linux():
    """Create necessary directories on Linux."""
    print_step("Creating directories...")

    directories = [
        INSTALL_DIR,
        CONFIG_DIR,
        DESKTOP_FILE.parent if DESKTOP_FILE else None,
        AUTOSTART_FILE.parent if AUTOSTART_FILE else None,
        SYSTEMD_SERVICE.parent if SYSTEMD_SERVICE else None,
        BIN_LINK.parent if BIN_LINK else None,
    ]

    for dir_path in directories:
        if dir_path:
            created = not dir_path.exists()
            dir_path.mkdir(parents=True, exist_ok=True)
            if created:
                print_verbose(f"Created {dir_path}")

    print_success("Directories created")


def create_directories():
    """Create necessary directories (platform-aware)."""
    if IS_WINDOWS:
        create_directories_windows()
    else:
        create_directories_linux()


def install_files():
    """Copy application files to installation directory."""
    print_step("Installing application files...")

    # Copy main script
    main_dest = INSTALL_DIR / "snipforge.py"
    shutil.copy2(SOURCE_FILES["main"], main_dest)
    if not IS_WINDOWS:
        main_dest.chmod(0o755)
    print_verbose(f"Copied {SOURCE_FILES['main']} → {main_dest}")

    # Copy icons to config directory
    # For app icon, prefer the ICO file and convert to PNG for Linux compatibility
    if SOURCE_FILES["icon_ico"].exists():
        dest = CONFIG_DIR / "app_icon.png"
        try:
            from PIL import Image
            img = Image.open(SOURCE_FILES["icon_ico"])
            # Get the largest size from the ICO file
            img.seek(0)
            largest = img
            for i in range(getattr(img, 'n_frames', 1)):
                img.seek(i)
                if img.size[0] > largest.size[0]:
                    largest = img.copy()
            # Convert to RGBA and save as PNG
            largest = largest.convert("RGBA")
            largest.save(dest, "PNG")
            print_verbose(f"Converted {SOURCE_FILES['icon_ico'].name} → {dest}")
        except Exception as e:
            print_verbose(f"Could not convert ICO to PNG: {e}")
            # Fall back to copying the old PNG if it exists
            if SOURCE_FILES["icon_png"].exists():
                shutil.copy2(SOURCE_FILES["icon_png"], dest)
                print_verbose(f"Copied {SOURCE_FILES['icon_png'].name} → {dest}")
    elif SOURCE_FILES["icon_png"].exists():
        dest = CONFIG_DIR / "app_icon.png"
        shutil.copy2(SOURCE_FILES["icon_png"], dest)
        print_verbose(f"Copied {SOURCE_FILES['icon_png'].name} → {dest}")

    if SOURCE_FILES["icon_ico"].exists():
        dest = CONFIG_DIR / "app_icon.ico"
        shutil.copy2(SOURCE_FILES["icon_ico"], dest)
        print_verbose(f"Copied {SOURCE_FILES['icon_ico'].name} → {dest}")

    if SOURCE_FILES["tray_ico"].exists():
        dest = CONFIG_DIR / "tray_icon.ico"
        shutil.copy2(SOURCE_FILES["tray_ico"], dest)
        print_verbose(f"Copied {SOURCE_FILES['tray_ico'].name} → {dest}")

    if SOURCE_FILES["logo_dark"].exists():
        dest = CONFIG_DIR / "background.png"
        shutil.copy2(SOURCE_FILES["logo_dark"], dest)
        print_verbose(f"Copied {SOURCE_FILES['logo_dark'].name} → {dest}")

    if SOURCE_FILES["logo_light"].exists():
        dest = CONFIG_DIR / "background_light.png"
        shutil.copy2(SOURCE_FILES["logo_light"], dest)
        print_verbose(f"Copied {SOURCE_FILES['logo_light'].name} → {dest}")

    print_success("Application files installed")


def create_launcher_script():
    """Create a launcher script (Linux only)."""
    if IS_WINDOWS:
        # Windows uses shortcuts instead
        return

    print_step("Creating launcher script...")

    launcher_content = f"""#!/bin/bash
# SnipForge launcher
exec python3 "{INSTALL_DIR / 'snipforge.py'}" "$@"
"""

    with open(BIN_LINK, "w") as f:
        f.write(launcher_content)

    BIN_LINK.chmod(0o755)
    print_success(f"Launcher created at {BIN_LINK}")


def create_start_menu_shortcut():
    """Create Start Menu shortcut (Windows only)."""
    if not IS_WINDOWS:
        return

    print_step("Creating Start Menu shortcut...")

    # Find pythonw.exe for windowless execution
    python_exe = shutil.which("pythonw")
    if not python_exe:
        python_exe = shutil.which("python")

    if not python_exe:
        print_warning("Could not find Python executable")
        return

    target = f'"{python_exe}" "{INSTALL_DIR / "snipforge.py"}"'
    icon = CONFIG_DIR / "app_icon.ico"

    success = create_windows_shortcut(
        shortcut_path=str(START_MENU_SHORTCUT),
        target_path=python_exe,
        working_dir=str(INSTALL_DIR),
        icon_path=str(icon) if icon.exists() else None,
        description=APP_DESCRIPTION
    )

    if success:
        # Update the shortcut to include the script argument
        # This requires a slightly different approach
        ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{START_MENU_SHORTCUT}")
$Shortcut.TargetPath = "{python_exe}"
$Shortcut.Arguments = '"{INSTALL_DIR / "snipforge.py"}"'
$Shortcut.WorkingDirectory = "{INSTALL_DIR}"
$Shortcut.IconLocation = "{icon}"
$Shortcut.Description = "{APP_DESCRIPTION}"
$Shortcut.Save()
'''
        try:
            subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True, text=True
            )
            print_success(f"Start Menu shortcut created")
        except Exception as e:
            print_warning(f"Failed to create Start Menu shortcut: {e}")
    else:
        print_warning("Failed to create Start Menu shortcut")


def create_startup_shortcut():
    """Create Startup folder shortcut for auto-start (Windows only)."""
    if not IS_WINDOWS:
        return

    print_step("Creating Startup shortcut...")

    # Find pythonw.exe for windowless execution
    python_exe = shutil.which("pythonw")
    if not python_exe:
        python_exe = shutil.which("python")

    if not python_exe:
        print_warning("Could not find Python executable")
        return

    icon = CONFIG_DIR / "app_icon.ico"

    ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{STARTUP_SHORTCUT}")
$Shortcut.TargetPath = "{python_exe}"
$Shortcut.Arguments = '"{INSTALL_DIR / "snipforge.py"}"'
$Shortcut.WorkingDirectory = "{INSTALL_DIR}"
$Shortcut.IconLocation = "{icon}"
$Shortcut.Description = "{APP_DESCRIPTION}"
$Shortcut.WindowStyle = 7
$Shortcut.Save()
'''
    try:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print_success(f"Startup shortcut created (auto-start enabled)")
        else:
            print_warning("Failed to create Startup shortcut")
    except Exception as e:
        print_warning(f"Failed to create Startup shortcut: {e}")


def create_desktop_entry():
    """Create the .desktop file for application menu (Linux only)."""
    if IS_WINDOWS:
        return

    print_step("Creating desktop entry...")

    desktop_content = f"""[Desktop Entry]
Version=1.1
Type=Application
Name={APP_DISPLAY_NAME}
GenericName=Text Expander
Comment={APP_DESCRIPTION}
Exec=python3 {INSTALL_DIR / 'snipforge.py'}
Icon={CONFIG_DIR / 'app_icon.png'}
Terminal=false
Categories=Utility;TextTools;
Keywords=snippet;text;expansion;clipboard;productivity;
StartupNotify=false
StartupWMClass={APP_NAME}
"""

    with open(DESKTOP_FILE, "w") as f:
        f.write(desktop_content)

    print_success(f"Desktop entry created at {DESKTOP_FILE}")


def create_autostart_entry():
    """Create autostart entry (Linux only)."""
    if IS_WINDOWS:
        return

    print_step("Creating autostart entry...")

    autostart_content = f"""[Desktop Entry]
Version=1.1
Type=Application
Name={APP_DISPLAY_NAME}
Comment={APP_DESCRIPTION}
Exec=python3 {INSTALL_DIR / 'snipforge.py'}
Icon={CONFIG_DIR / 'app_icon.png'}
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
StartupWMClass={APP_NAME}
"""

    with open(AUTOSTART_FILE, "w") as f:
        f.write(autostart_content)

    print_success(f"Autostart entry created at {AUTOSTART_FILE}")


def create_systemd_service():
    """Create systemd user service (Linux only)."""
    if IS_WINDOWS:
        return

    print_step("Creating systemd user service...")

    service_content = f"""[Unit]
Description={APP_DISPLAY_NAME} - {APP_DESCRIPTION}
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 {INSTALL_DIR / 'snipforge.py'}
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0
Environment=YDOTOOL_SOCKET=/tmp/.ydotool_socket

[Install]
WantedBy=graphical-session.target
"""

    with open(SYSTEMD_SERVICE, "w") as f:
        f.write(service_content)

    print_success(f"Systemd service created at {SYSTEMD_SERVICE}")


def setup_input_group():
    """Add user to input group for evdev access (Linux/Wayland only).

    Returns:
        'already' - user was already in the group
        'added' - user was just added (needs logout)
        'skipped' - user declined or error occurred
        None - not applicable (Windows)
    """
    if IS_WINDOWS:
        return None

    print_step("Checking input group membership...")

    username = os.environ.get("USER", os.environ.get("LOGNAME"))
    if not username:
        print_warning("Could not determine username, skipping input group setup")
        return 'skipped'

    # Check if already in input group
    result = run_command(["groups", username], check=False)
    if result.returncode == 0 and "input" in result.stdout:
        print_info("User already in 'input' group")
        return 'already'

    print_info("Adding user to 'input' group for Wayland keyboard access...")
    print_info("This requires sudo and you'll need to log out/in for it to take effect.")

    if prompt_yes_no(f"Add {username} to input group?", default=False):
        try:
            run_command(["usermod", "-aG", "input", username], sudo=True)
            print_success(f"User '{username}' added to 'input' group")
            return 'added'
        except subprocess.CalledProcessError:
            print_warning("Failed to add user to input group")
            print_info("You can manually run: sudo usermod -aG input $USER")
            return 'skipped'
    else:
        print_info("Skipped. You can manually run: sudo usermod -aG input $USER")
        return 'skipped'


def enable_service():
    """Enable and optionally start the systemd service (Linux only)."""
    if IS_WINDOWS:
        return

    print_step("Enabling systemd service...")

    # Reload systemd user daemon
    run_command(["systemctl", "--user", "daemon-reload"], check=False)

    # Enable service
    result = run_command(["systemctl", "--user", "enable", APP_NAME], check=False)
    if result.returncode == 0:
        print_success("Systemd service enabled")

    # Ask about starting now
    if prompt_yes_no(f"Start {APP_DISPLAY_NAME} now?", default=True):
        run_command(["systemctl", "--user", "start", APP_NAME], check=False)
        print_success(f"{APP_DISPLAY_NAME} started!")


def update_desktop_database():
    """Update desktop database for application menu (Linux only)."""
    if IS_WINDOWS:
        return

    print_step("Updating desktop database...")

    if command_exists("update-desktop-database"):
        run_command([
            "update-desktop-database",
            str(Path.home() / ".local" / "share" / "applications")
        ], check=False)
        print_success("Desktop database updated")
    else:
        print_info("update-desktop-database not found, skipping")


# ============================================================================
# Uninstallation Functions
# ============================================================================

def uninstall():
    """Uninstall SnipForge."""
    print_header(f"Uninstalling {APP_DISPLAY_NAME}")

    if IS_WINDOWS:
        uninstall_windows()
    else:
        uninstall_linux()


def uninstall_windows():
    """Uninstall SnipForge on Windows."""
    # Remove shortcuts
    print_step("Removing shortcuts...")

    shortcuts_to_remove = [
        START_MENU_SHORTCUT,
        STARTUP_SHORTCUT,
    ]

    for shortcut in shortcuts_to_remove:
        if shortcut and shortcut.exists():
            shortcut.unlink()
            print_info(f"Removed {shortcut}")

    # Remove install directory
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
        print_info(f"Removed {INSTALL_DIR}")

    # Ask about config
    if CONFIG_DIR.exists():
        if prompt_yes_no(f"Remove configuration and snippets at {CONFIG_DIR}?", default=False):
            shutil.rmtree(CONFIG_DIR)
            print_info(f"Removed {CONFIG_DIR}")
        else:
            print_info("Configuration preserved")

    print_success(f"{APP_DISPLAY_NAME} uninstalled successfully!")


def uninstall_linux():
    """Uninstall SnipForge on Linux."""
    # Stop and disable service
    print_step("Stopping service...")
    run_command(["systemctl", "--user", "stop", APP_NAME], check=False)
    run_command(["systemctl", "--user", "disable", APP_NAME], check=False)

    # Remove files
    files_to_remove = [
        SYSTEMD_SERVICE,
        DESKTOP_FILE,
        AUTOSTART_FILE,
        BIN_LINK,
    ]

    print_step("Removing files...")
    for f in files_to_remove:
        if f and f.exists():
            f.unlink()
            print_info(f"Removed {f}")

    # Remove install directory
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
        print_info(f"Removed {INSTALL_DIR}")

    # Ask about config
    if CONFIG_DIR.exists():
        if prompt_yes_no(f"Remove configuration and snippets at {CONFIG_DIR}?", default=False):
            shutil.rmtree(CONFIG_DIR)
            print_info(f"Removed {CONFIG_DIR}")
        else:
            print_info("Configuration preserved")

    # Reload systemd
    run_command(["systemctl", "--user", "daemon-reload"], check=False)
    update_desktop_database()

    print_success(f"{APP_DISPLAY_NAME} uninstalled successfully!")


# ============================================================================
# Status Check
# ============================================================================

def check_status():
    """Check installation status."""
    print_header(f"{APP_DISPLAY_NAME} Installation Status")

    if IS_WINDOWS:
        check_status_windows()
    else:
        check_status_linux()


def check_status_windows():
    """Check installation status on Windows."""
    # Check files
    checks = [
        ("Application installed", (INSTALL_DIR / "snipforge.py").exists()),
        ("Start Menu shortcut", START_MENU_SHORTCUT.exists() if START_MENU_SHORTCUT else False),
        ("Startup shortcut (auto-start)", STARTUP_SHORTCUT.exists() if STARTUP_SHORTCUT else False),
        ("Config directory", CONFIG_DIR.exists()),
    ]

    print(f"{Colors.BOLD}Files:{Colors.RESET}")
    for name, exists in checks:
        status = f"{Colors.GREEN}✓{Colors.RESET}" if exists else f"{Colors.RED}✗{Colors.RESET}"
        print(f"  {status} {name}")

    # Check dependencies
    print(f"\n{Colors.BOLD}Dependencies:{Colors.RESET}")
    distro = type('obj', (object,), {'family': 'windows'})()  # Dummy distro object
    dep_manager = DependencyManager(distro)
    missing = dep_manager.check_dependencies()

    modules = ["PyQt5", "pynput", "pyperclip", "PIL", "pywin32"]
    for mod in modules:
        mod_name = mod if mod != "pywin32" else "win32api"
        installed = mod_name not in missing
        status = f"{Colors.GREEN}✓{Colors.RESET}" if installed else f"{Colors.RED}✗{Colors.RESET}"
        print(f"  {status} {mod}")

    # Check if process is running
    print(f"\n{Colors.BOLD}Process Status:{Colors.RESET}")
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq pythonw.exe", "/FO", "CSV"],
            capture_output=True, text=True
        )
        running = "snipforge" in result.stdout.lower() or "pythonw" in result.stdout.lower()
        # Better check - look for snipforge in window titles
        result2 = subprocess.run(
            ["powershell", "-Command", "Get-Process | Where-Object {$_.MainWindowTitle -like '*SnipForge*'}"],
            capture_output=True, text=True
        )
        running = "SnipForge" in result2.stdout or running
    except Exception:
        running = False

    status = f"{Colors.GREEN}running{Colors.RESET}" if running else f"{Colors.YELLOW}not detected{Colors.RESET}"
    print(f"  Status: {status}")


def check_status_linux():
    """Check installation status on Linux."""
    # Check files
    checks = [
        ("Application installed", (INSTALL_DIR / "snipforge.py").exists()),
        ("Desktop entry", DESKTOP_FILE.exists() if DESKTOP_FILE else False),
        ("Autostart entry", AUTOSTART_FILE.exists() if AUTOSTART_FILE else False),
        ("Systemd service", SYSTEMD_SERVICE.exists() if SYSTEMD_SERVICE else False),
        ("Launcher script", BIN_LINK.exists() if BIN_LINK else False),
        ("Config directory", CONFIG_DIR.exists()),
    ]

    print(f"{Colors.BOLD}Files:{Colors.RESET}")
    for name, exists in checks:
        status = f"{Colors.GREEN}✓{Colors.RESET}" if exists else f"{Colors.RED}✗{Colors.RESET}"
        print(f"  {status} {name}")

    # Check service status
    print(f"\n{Colors.BOLD}Service Status:{Colors.RESET}")
    result = run_command(["systemctl", "--user", "is-enabled", APP_NAME], check=False)
    enabled = result.returncode == 0
    status = f"{Colors.GREEN}enabled{Colors.RESET}" if enabled else f"{Colors.YELLOW}disabled{Colors.RESET}"
    print(f"  Service: {status}")

    result = run_command(["systemctl", "--user", "is-active", APP_NAME], check=False)
    active = result.returncode == 0
    status = f"{Colors.GREEN}running{Colors.RESET}" if active else f"{Colors.RED}stopped{Colors.RESET}"
    print(f"  Status: {status}")

    # Check dependencies
    print(f"\n{Colors.BOLD}Dependencies:{Colors.RESET}")
    dep_manager = DependencyManager(Distro())
    missing = dep_manager.check_dependencies()

    modules = ["PyQt5", "pynput", "pyperclip", "PIL", "evdev"]
    for mod in modules:
        installed = mod not in missing
        status = f"{Colors.GREEN}✓{Colors.RESET}" if installed else f"{Colors.RED}✗{Colors.RESET}"
        print(f"  {status} {mod}")

    # Check input group
    print(f"\n{Colors.BOLD}Input Group:{Colors.RESET}")
    username = os.environ.get("USER", "")
    result = run_command(["groups", username], check=False)
    in_group = "input" in result.stdout if result.returncode == 0 else False
    status = f"{Colors.GREEN}✓ member{Colors.RESET}" if in_group else f"{Colors.YELLOW}✗ not member{Colors.RESET}"
    print(f"  {status}")


# ============================================================================
# Version Management
# ============================================================================

def get_version_from_file(filepath):
    """Extract __version__ from a Python file."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        if match:
            return match.group(1)
    except (IOError, OSError):
        pass
    return None


def get_installed_version():
    """Get the version of the installed SnipForge."""
    installed_script = INSTALL_DIR / "snipforge.py"
    if installed_script.exists():
        return get_version_from_file(installed_script)
    return None


def get_source_version():
    """Get the version from the source snipforge.py."""
    if SOURCE_FILES["main"].exists():
        return get_version_from_file(SOURCE_FILES["main"])
    return None


def get_github_latest_version():
    """Fetch the latest release version from GitHub."""
    try:
        with urlopen(GITHUB_API_URL, timeout=5) as response:
            data = json.loads(response.read().decode())
            tag = data.get("tag_name", "")
            # Remove 'v' prefix if present
            return tag.lstrip("v") if tag else None
    except (URLError, json.JSONDecodeError, KeyError, TimeoutError):
        return None


def compare_versions(v1, v2):
    """
    Compare two version strings.
    Returns: -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
    """
    def parse_version(v):
        return [int(x) for x in v.split(".")]

    try:
        p1, p2 = parse_version(v1), parse_version(v2)
        if p1 < p2:
            return -1
        elif p1 > p2:
            return 1
        return 0
    except (ValueError, AttributeError):
        return 0


def check_version():
    """Display version information and check for updates."""
    print_header(f"{APP_DISPLAY_NAME} Version Information")

    installed = get_installed_version()
    source = get_source_version()
    latest = get_github_latest_version()

    print(f"{Colors.BOLD}Versions:{Colors.RESET}")

    # Installed version
    if installed:
        print(f"  Installed:  {Colors.GREEN}{installed}{Colors.RESET}")
    else:
        print(f"  Installed:  {Colors.YELLOW}not installed{Colors.RESET}")

    # Source version
    if source:
        print(f"  Source:     {Colors.CYAN}{source}{Colors.RESET}")
    else:
        print(f"  Source:     {Colors.YELLOW}not found{Colors.RESET}")

    # GitHub latest
    if latest:
        print(f"  Latest:     {Colors.BLUE}{latest}{Colors.RESET} (GitHub)")
    else:
        print(f"  Latest:     {Colors.YELLOW}unable to check{Colors.RESET}")

    # Installer version
    print(f"  Installer:  {APP_VERSION}")

    # Update recommendations
    print(f"\n{Colors.BOLD}Status:{Colors.RESET}")

    if not installed:
        print_info("SnipForge is not installed. Run: python install.py install")
    elif source and compare_versions(installed, source) < 0:
        print_warning(f"Source version ({source}) is newer than installed ({installed})")
        print_info("Run: python install.py update")
    elif latest and compare_versions(installed, latest) < 0:
        print_warning(f"A new version ({latest}) is available on GitHub!")
        print_info("Run: git pull && python install.py update")
    else:
        print_success("You are running the latest version")


# ============================================================================
# Backup and Restore
# ============================================================================

def list_backups():
    """List available backups."""
    if not BACKUP_DIR.exists():
        return []

    backups = sorted(BACKUP_DIR.glob("*.tar.gz"), reverse=True)
    return backups


def backup_config(output_path=None):
    """Create a backup of the configuration directory."""
    print_header(f"{APP_DISPLAY_NAME} Backup")

    if not CONFIG_DIR.exists():
        print_error(f"Configuration directory not found: {CONFIG_DIR}")
        return False

    # Create backup directory
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Generate backup filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_path:
        backup_file = Path(output_path)
    else:
        backup_file = BACKUP_DIR / f"snipforge_backup_{timestamp}.tar.gz"

    print_step(f"Creating backup of {CONFIG_DIR}...")

    try:
        with tarfile.open(backup_file, "w:gz") as tar:
            # Add config directory contents
            for item in CONFIG_DIR.iterdir():
                arcname = item.name
                tar.add(item, arcname=arcname)
                print_verbose(f"Added: {item.name}")

        size_kb = backup_file.stat().st_size / 1024
        print_success(f"Backup created: {backup_file}")
        print_info(f"Size: {size_kb:.1f} KB")

        # List recent backups
        backups = list_backups()
        if len(backups) > 1:
            print(f"\n{Colors.BOLD}Available backups:{Colors.RESET}")
            for b in backups[:5]:
                print(f"  - {b.name}")
            if len(backups) > 5:
                print(f"  ... and {len(backups) - 5} more")

        return True

    except (OSError, tarfile.TarError) as e:
        print_error(f"Backup failed: {e}")
        return False


def restore_config(backup_path=None):
    """Restore configuration from a backup."""
    print_header(f"{APP_DISPLAY_NAME} Restore")

    # Find backup file
    if backup_path:
        backup_file = Path(backup_path)
        if not backup_file.exists():
            print_error(f"Backup file not found: {backup_file}")
            return False
    else:
        # Use most recent backup
        backups = list_backups()
        if not backups:
            print_error("No backups found")
            print_info(f"Backup directory: {BACKUP_DIR}")
            return False

        backup_file = backups[0]
        print_info(f"Using most recent backup: {backup_file.name}")

    # Confirm restore
    if CONFIG_DIR.exists():
        if not prompt_yes_no(f"This will overwrite {CONFIG_DIR}. Continue?", default=False):
            print_info("Restore cancelled")
            return False

    print_step(f"Restoring from {backup_file.name}...")

    try:
        # Create config directory if needed
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Extract backup
        with tarfile.open(backup_file, "r:gz") as tar:
            # Safety check: ensure no path traversal
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    print_error(f"Invalid path in backup: {member.name}")
                    return False

            tar.extractall(path=CONFIG_DIR)
            print_verbose(f"Extracted {len(tar.getmembers())} items")

        print_success("Configuration restored successfully")
        print_info("Restart SnipForge to apply changes")
        return True

    except (OSError, tarfile.TarError) as e:
        print_error(f"Restore failed: {e}")
        return False


def show_backups():
    """Display list of available backups."""
    print_header(f"{APP_DISPLAY_NAME} Backups")

    backups = list_backups()

    if not backups:
        print_info("No backups found")
        print_info(f"Create one with: python install.py backup")
        return

    print(f"{Colors.BOLD}Available backups:{Colors.RESET}\n")
    for i, backup in enumerate(backups, 1):
        size_kb = backup.stat().st_size / 1024
        mtime = datetime.fromtimestamp(backup.stat().st_mtime)
        date_str = mtime.strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {i}. {backup.name}")
        print(f"     {Colors.CYAN}{date_str}{Colors.RESET} ({size_kb:.1f} KB)")

    print(f"\n{Colors.BOLD}Usage:{Colors.RESET}")
    print(f"  Restore latest:   python install.py restore")
    print(f"  Restore specific: python install.py restore <filename>")


# ============================================================================
# Import and Export Snippets
# ============================================================================

SNIPPETS_FILE = CONFIG_DIR / "snippets.json"


def export_snippets(output_path=None):
    """Export snippets to a JSON file."""
    print_header(f"{APP_DISPLAY_NAME} Export Snippets")

    if not SNIPPETS_FILE.exists():
        print_error(f"Snippets file not found: {SNIPPETS_FILE}")
        print_info("No snippets to export")
        return False

    # Determine output path
    if output_path:
        output_file = Path(output_path)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = Path.cwd() / f"snipforge_snippets_{timestamp}.json"

    print_step(f"Reading snippets from {SNIPPETS_FILE}...")

    try:
        with open(SNIPPETS_FILE, 'r') as f:
            snippets = json.load(f)

        # Add export metadata
        export_data = {
            "version": APP_VERSION,
            "exported_at": datetime.now().isoformat(),
            "snippet_count": len(snippets),
            "snippets": snippets
        }

        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2)

        print_success(f"Exported {len(snippets)} snippets to {output_file}")
        return True

    except (OSError, json.JSONDecodeError) as e:
        print_error(f"Export failed: {e}")
        return False


def import_snippets(input_path, merge=True):
    """Import snippets from a JSON file."""
    print_header(f"{APP_DISPLAY_NAME} Import Snippets")

    input_file = Path(input_path)
    if not input_file.exists():
        print_error(f"Import file not found: {input_file}")
        return False

    print_step(f"Reading snippets from {input_file}...")

    try:
        with open(input_file, 'r') as f:
            import_data = json.load(f)

        # Handle both raw snippet arrays and export format with metadata
        if isinstance(import_data, list):
            new_snippets = import_data
        elif isinstance(import_data, dict) and "snippets" in import_data:
            new_snippets = import_data["snippets"]
            if "version" in import_data:
                print_info(f"Import file version: {import_data.get('version')}")
            if "snippet_count" in import_data:
                print_info(f"Contains {import_data.get('snippet_count')} snippets")
        else:
            print_error("Invalid import file format")
            return False

        # Validate snippets structure
        for i, snippet in enumerate(new_snippets):
            if not isinstance(snippet, dict):
                print_error(f"Invalid snippet at index {i}")
                return False
            if "trigger" not in snippet or "content" not in snippet:
                print_error(f"Snippet at index {i} missing required fields (trigger, content)")
                return False

        # Load existing snippets
        existing_snippets = []
        if SNIPPETS_FILE.exists() and merge:
            with open(SNIPPETS_FILE, 'r') as f:
                existing_snippets = json.load(f)
            print_info(f"Existing snippets: {len(existing_snippets)}")

        if merge and existing_snippets:
            # Merge: add new snippets, skip duplicates by trigger
            existing_triggers = {s.get("trigger") for s in existing_snippets}
            added = 0
            skipped = 0

            for snippet in new_snippets:
                if snippet.get("trigger") in existing_triggers:
                    print_verbose(f"Skipping duplicate trigger: {snippet.get('trigger')}")
                    skipped += 1
                else:
                    existing_snippets.append(snippet)
                    existing_triggers.add(snippet.get("trigger"))
                    added += 1

            final_snippets = existing_snippets
            print_info(f"Added: {added}, Skipped (duplicates): {skipped}")
        else:
            # Replace mode
            if existing_snippets:
                if not prompt_yes_no(f"Replace {len(existing_snippets)} existing snippets?", default=False):
                    print_info("Import cancelled")
                    return False
            final_snippets = new_snippets

        # Ensure config directory exists
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Write snippets
        with open(SNIPPETS_FILE, 'w') as f:
            json.dump(final_snippets, f, indent=2)

        print_success(f"Imported snippets. Total: {len(final_snippets)}")
        print_info("Restart SnipForge to apply changes")
        return True

    except (OSError, json.JSONDecodeError) as e:
        print_error(f"Import failed: {e}")
        return False


# ============================================================================
# Main Installation Flow
# ============================================================================

def install():
    """Run the full installation process."""
    print_header(f"Installing {APP_DISPLAY_NAME}")

    if IS_WINDOWS:
        return install_windows()
    else:
        return install_linux()


def install_windows():
    """Run Windows installation."""
    print_info(f"Platform: Windows")

    # Check source files
    if not check_source_files():
        print_error("Installation aborted: missing source files")
        return False

    # Install dependencies via pip
    distro = type('obj', (object,), {'family': 'windows', 'name': 'Windows'})()
    dep_manager = DependencyManager(distro)

    missing = dep_manager.check_dependencies()
    if missing:
        print_info(f"Missing dependencies: {', '.join(missing)}")
        if prompt_yes_no("Install dependencies via pip?", default=True):
            if not dep_manager.install_pip_packages():
                print_error("Failed to install dependencies")
                return False
        else:
            print_warning("Skipping dependency installation")
    else:
        print_success("All dependencies already installed")

    # Create directories
    create_directories()

    # Install files
    install_files()

    # Create Start Menu shortcut
    create_start_menu_shortcut()

    # Ask about auto-start
    if prompt_yes_no("Enable auto-start on Windows login?", default=True):
        create_startup_shortcut()

    # Done!
    print_header("Installation Complete!")
    print_success(f"{APP_DISPLAY_NAME} has been installed successfully!")
    print()
    print_info("You can start it from:")
    print(f"    - Start Menu: {APP_DISPLAY_NAME}")
    print(f"    - Run directly: pythonw \"{INSTALL_DIR / 'snipforge.py'}\"")
    print()
    print_info("Configuration stored at:")
    print(f"    {CONFIG_DIR}")
    print()

    # Offer to start now
    if prompt_yes_no(f"Start {APP_DISPLAY_NAME} now?", default=True):
        try:
            python_exe = shutil.which("pythonw") or shutil.which("python")
            subprocess.Popen(
                [python_exe, str(INSTALL_DIR / "snipforge.py")],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
            )
            print_success(f"{APP_DISPLAY_NAME} started!")
        except Exception as e:
            print_warning(f"Could not start automatically: {e}")
            print_info(f"Please start manually from the Start Menu")

    return True


def install_linux():
    """Run Linux installation."""
    # Detect distro
    distro = Distro()
    print_info(f"Detected: {distro}")

    if distro.family == Distro.FAMILY_UNKNOWN:
        print_warning("Unknown distribution, will attempt pip-based installation")

    # Check source files
    if not check_source_files():
        print_error("Installation aborted: missing source files")
        return False

    # Install dependencies
    dep_manager = DependencyManager(distro)

    # Check if deps already installed FIRST
    print_step("Checking dependencies...")
    missing = dep_manager.check_dependencies()
    if missing:
        print_info(f"Missing Python dependencies: {', '.join(missing)}")
        if prompt_yes_no("Install dependencies?", default=True):
            if not dep_manager.install_system_packages():
                # Final check - maybe some things installed despite errors
                still_missing = dep_manager.check_dependencies()
                if still_missing:
                    print_error(f"Failed to install dependencies: {', '.join(still_missing)}")
                    print_info("You can install them manually and run the installer again.")
                    return False
                else:
                    print_success("All dependencies are now installed")
        else:
            print_warning("Skipping dependency installation")
            print_warning("SnipForge may not work without these dependencies!")
    else:
        print_success("All dependencies already installed")

    # Create directories
    create_directories()

    # Install files
    install_files()

    # Create launcher
    create_launcher_script()

    # Create desktop entry
    create_desktop_entry()

    # Create autostart
    create_autostart_entry()

    # Create systemd service
    create_systemd_service()

    # Setup input group for Wayland
    input_group_status = setup_input_group()

    # Enable service
    enable_service()

    # Update desktop database
    update_desktop_database()

    # Done!
    print_header("Installation Complete!")
    print_success(f"{APP_DISPLAY_NAME} has been installed successfully!")
    print()

    # Show prominent warning if user was just added to input group
    if input_group_status == 'added':
        print()
        print(f"{Colors.BOLD}{Colors.YELLOW}{'=' * 60}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.YELLOW}  IMPORTANT: LOG OUT AND BACK IN BEFORE USING!{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.YELLOW}{'=' * 60}{Colors.RESET}")
        print()
        print(f"{Colors.YELLOW}  You were added to the 'input' group for keyboard access.{Colors.RESET}")
        print(f"{Colors.YELLOW}  SnipForge will NOT work until you log out and back in.{Colors.RESET}")
        print()

    print_info("You can start it from:")
    print(f"    - Application menu: {APP_DISPLAY_NAME}")
    print(f"    - Command line: {BIN_LINK}")
    print(f"    - Systemd: systemctl --user start {APP_NAME}")
    print()
    print_info("Configuration stored at:")
    print(f"    {CONFIG_DIR}")
    print()

    if not (Path.home() / ".local" / "bin").as_posix() in os.environ.get("PATH", ""):
        print_warning(f"Note: {Path.home() / '.local' / 'bin'} may not be in your PATH")
        print_info("Add to your shell profile: export PATH=\"$HOME/.local/bin:$PATH\"")

    return True


def update():
    """Update SnipForge to the latest version."""
    print_header(f"Updating {APP_DISPLAY_NAME}")

    # Check versions
    installed = get_installed_version()
    source = get_source_version()

    if not installed:
        print_error("SnipForge is not installed")
        print_info("Run: python install.py install")
        return False

    if not source:
        print_error("Source files not found")
        return False

    print_info(f"Installed version: {installed}")
    print_info(f"Source version: {source}")

    # Compare versions
    cmp = compare_versions(installed, source)
    if cmp >= 0:
        print_success("You already have the latest version")
        return True

    print_info(f"Update available: {installed} → {source}")

    # Offer backup
    if prompt_yes_no("Create backup before updating?", default=True):
        print_step("Creating backup...")
        if not backup_config():
            if not prompt_yes_no("Backup failed. Continue anyway?", default=False):
                return False

    if IS_WINDOWS:
        # Windows update
        print_step("Updating application files...")
        install_files()

        print_info("Please restart SnipForge to apply the update")
    else:
        # Linux update
        # Stop service if running
        print_step("Stopping service...")
        run_command(["systemctl", "--user", "stop", APP_NAME], check=False)

        # Update files
        print_step("Updating application files...")
        install_files()

        # Restart service
        print_step("Starting service...")
        run_command(["systemctl", "--user", "start", APP_NAME], check=False)

    # Verify
    new_version = get_installed_version()
    if new_version == source:
        print_success(f"Successfully updated to version {new_version}")
    else:
        print_warning("Update completed but version mismatch detected")

    return True


# ============================================================================
# Entry Point
# ============================================================================

def install_deps_only():
    """Install only dependencies without full installation."""
    print_header(f"Installing {APP_DISPLAY_NAME} Dependencies")

    if IS_WINDOWS:
        print_info("Platform: Windows")
        distro = type('obj', (object,), {'family': 'windows', 'name': 'Windows'})()
    else:
        distro = Distro()
        print_info(f"Detected: {distro}")

    dep_manager = DependencyManager(distro)
    missing = dep_manager.check_dependencies()

    if not missing:
        print_success("All dependencies already installed")
        return True

    print_info(f"Missing dependencies: {', '.join(missing)}")

    if IS_WINDOWS:
        # Windows: always use pip
        if dep_manager.install_pip_packages():
            print_success("Dependencies installed successfully")
            return True
        else:
            print_error("Failed to install dependencies")
            return False
    else:
        # Linux: try system packages first
        if dep_manager.install_system_packages():
            print_success("Dependencies installed successfully")
            return True
        else:
            print_error("Failed to install dependencies")
            return False


def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_DISPLAY_NAME} Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python install.py install          Install SnipForge
    python install.py uninstall        Uninstall SnipForge
    python install.py update           Update to latest version
    python install.py status           Check installation status
    python install.py version          Show version information
    python install.py backup           Backup configuration
    python install.py backup --list    List available backups
    python install.py restore          Restore from latest backup
    python install.py export           Export snippets to JSON
    python install.py import file.json Import snippets from JSON
    python install.py deps             Install dependencies only
    python install.py -v install       Verbose installation
"""
    )

    parser.add_argument(
        "action",
        nargs="?",
        default="install",
        choices=["install", "uninstall", "update", "status", "version", "backup", "restore", "export", "import", "deps"],
        help="Action to perform (default: install)"
    )

    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Optional file path for backup/restore/import/export operations"
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_DISPLAY_NAME} Installer v{APP_VERSION}"
    )

    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Automatic yes to prompts (non-interactive mode)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed output"
    )

    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List available backups (use with 'backup' action)"
    )

    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing snippets instead of merging (use with 'import' action)"
    )

    args = parser.parse_args()

    # Set global flags
    global AUTO_YES, VERBOSE
    AUTO_YES = args.yes
    VERBOSE = args.verbose

    # Platform info
    if IS_WINDOWS:
        print_info("Platform: Windows")
    elif IS_LINUX:
        pass  # Will be shown by Distro detection
    elif IS_MACOS:
        print_error("macOS is not yet supported")
        sys.exit(1)
    else:
        print_warning("Unknown platform, attempting installation anyway")

    # Run action
    try:
        if args.action == "install":
            success = install()
            sys.exit(0 if success else 1)
        elif args.action == "uninstall":
            uninstall()
        elif args.action == "update":
            success = update()
            sys.exit(0 if success else 1)
        elif args.action == "status":
            check_status()
        elif args.action == "version":
            check_version()
        elif args.action == "backup":
            if args.list:
                show_backups()
            else:
                success = backup_config(args.file)
                sys.exit(0 if success else 1)
        elif args.action == "restore":
            success = restore_config(args.file)
            sys.exit(0 if success else 1)
        elif args.action == "export":
            success = export_snippets(args.file)
            sys.exit(0 if success else 1)
        elif args.action == "import":
            if not args.file:
                print_error("Import requires a file path")
                print_info("Usage: python install.py import <file.json>")
                sys.exit(1)
            success = import_snippets(args.file, merge=not args.replace)
            sys.exit(0 if success else 1)
        elif args.action == "deps":
            success = install_deps_only()
            sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nOperation cancelled")
        sys.exit(130)


if __name__ == "__main__":
    main()
