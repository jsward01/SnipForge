#!/usr/bin/env python3
"""
SnipForge Installer
Cross-platform installer for Linux distributions.

Supported distros:
- Arch-based (CachyOS, Manjaro, EndeavourOS, etc.)
- Debian-based (Debian, Ubuntu, Pop!_OS, Linux Mint, LMDE, etc.)
- Fedora-based (Fedora, RHEL, CentOS Stream, etc.)

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
from pathlib import Path


# ============================================================================
# Configuration
# ============================================================================

APP_NAME = "snipforge"
APP_DISPLAY_NAME = "SnipForge"
APP_DESCRIPTION = "Forge your snippets - Quick text expansion tool"
APP_VERSION = "1.0.0"

# Global flags (set by argument parser)
AUTO_YES = False  # --yes flag for non-interactive mode

# Installation paths
INSTALL_DIR = Path.home() / ".local" / "share" / APP_NAME
CONFIG_DIR = Path.home() / ".config" / APP_NAME
DESKTOP_FILE = Path.home() / ".local" / "share" / "applications" / f"{APP_NAME}.desktop"
AUTOSTART_FILE = Path.home() / ".config" / "autostart" / f"{APP_NAME}.desktop"
SYSTEMD_SERVICE = Path.home() / ".config" / "systemd" / "user" / f"{APP_NAME}.service"
BIN_LINK = Path.home() / ".local" / "bin" / APP_NAME

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
    PIP_PACKAGES = [
        "PyQt5",
        "pynput",
        "pyperclip",
        "Pillow",
        "evdev",
    ]

    def __init__(self, distro):
        self.distro = distro

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
                run_command(["apt", "update"], sudo=True, capture=False)
                run_command(["apt", "install", "-y"] + packages, sudo=True, capture=False)

            elif pkg_manager == "dnf":
                run_command(["dnf", "install", "-y"] + packages, sudo=True, capture=False)

            print_success("System packages installed")
            return True

        except subprocess.CalledProcessError as e:
            print_error(f"Failed to install system packages")
            print_info("Falling back to pip installation...")
            return self.install_pip_packages()

    def install_pip_packages(self):
        """Install packages via pip as fallback."""
        print_step("Installing Python packages via pip...")

        try:
            run_command([
                sys.executable, "-m", "pip", "install", "--user", "--upgrade"
            ] + self.PIP_PACKAGES, capture=False)
            print_success("Python packages installed via pip")
            return True
        except subprocess.CalledProcessError:
            print_error("Failed to install Python packages")
            return False

    def check_dependencies(self):
        """Check if all required Python modules are available."""
        missing = []
        modules = ["PyQt5", "pynput", "pyperclip", "PIL", "evdev"]

        for module in modules:
            try:
                __import__(module if module != "PIL" else "PIL")
            except ImportError:
                missing.append(module)

        return missing


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


def create_directories():
    """Create necessary directories."""
    print_step("Creating directories...")

    directories = [
        INSTALL_DIR,
        CONFIG_DIR,
        DESKTOP_FILE.parent,
        AUTOSTART_FILE.parent,
        SYSTEMD_SERVICE.parent,
        BIN_LINK.parent,
    ]

    for dir_path in directories:
        dir_path.mkdir(parents=True, exist_ok=True)

    print_success("Directories created")


def install_files():
    """Copy application files to installation directory."""
    print_step("Installing application files...")

    # Copy main script
    main_dest = INSTALL_DIR / "snipforge.py"
    shutil.copy2(SOURCE_FILES["main"], main_dest)
    main_dest.chmod(0o755)

    # Copy icons to config directory
    if SOURCE_FILES["icon_png"].exists():
        shutil.copy2(SOURCE_FILES["icon_png"], CONFIG_DIR / "app_icon.png")

    if SOURCE_FILES["icon_ico"].exists():
        shutil.copy2(SOURCE_FILES["icon_ico"], CONFIG_DIR / "app_icon.ico")

    if SOURCE_FILES["tray_ico"].exists():
        shutil.copy2(SOURCE_FILES["tray_ico"], CONFIG_DIR / "tray_icon.ico")

    if SOURCE_FILES["logo_dark"].exists():
        shutil.copy2(SOURCE_FILES["logo_dark"], CONFIG_DIR / "background.png")

    if SOURCE_FILES["logo_light"].exists():
        shutil.copy2(SOURCE_FILES["logo_light"], CONFIG_DIR / "background_light.png")

    print_success("Application files installed")


def create_launcher_script():
    """Create a launcher script in ~/.local/bin."""
    print_step("Creating launcher script...")

    launcher_content = f"""#!/bin/bash
# SnipForge launcher
exec python3 "{INSTALL_DIR / 'snipforge.py'}" "$@"
"""

    with open(BIN_LINK, "w") as f:
        f.write(launcher_content)

    BIN_LINK.chmod(0o755)
    print_success(f"Launcher created at {BIN_LINK}")


def create_desktop_entry():
    """Create the .desktop file for application menu."""
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
    """Create autostart entry."""
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
    """Create systemd user service."""
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
    """Add user to input group for evdev access (Wayland)."""
    print_step("Checking input group membership...")

    username = os.environ.get("USER", os.environ.get("LOGNAME"))
    if not username:
        print_warning("Could not determine username, skipping input group setup")
        return

    # Check if already in input group
    result = run_command(["groups", username], check=False)
    if result.returncode == 0 and "input" in result.stdout:
        print_info("User already in 'input' group")
        return

    print_info("Adding user to 'input' group for Wayland keyboard access...")
    print_info("This requires sudo and you'll need to log out/in for it to take effect.")

    if prompt_yes_no(f"Add {username} to input group?", default=False):
        try:
            run_command(["usermod", "-aG", "input", username], sudo=True)
            print_success(f"User '{username}' added to 'input' group")
            print_warning("You must log out and back in for this to take effect!")
        except subprocess.CalledProcessError:
            print_warning("Failed to add user to input group")
            print_info("You can manually run: sudo usermod -aG input $USER")
    else:
        print_info("Skipped. You can manually run: sudo usermod -aG input $USER")


def enable_service():
    """Enable and optionally start the systemd service."""
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
    """Update desktop database for application menu."""
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
        if f.exists():
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

    # Check files
    checks = [
        ("Application installed", (INSTALL_DIR / "snipforge.py").exists()),
        ("Desktop entry", DESKTOP_FILE.exists()),
        ("Autostart entry", AUTOSTART_FILE.exists()),
        ("Systemd service", SYSTEMD_SERVICE.exists()),
        ("Launcher script", BIN_LINK.exists()),
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
# Main Installation Flow
# ============================================================================

def install():
    """Run the full installation process."""
    print_header(f"Installing {APP_DISPLAY_NAME}")

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

    # Check if deps already installed
    missing = dep_manager.check_dependencies()
    if missing:
        print_info(f"Missing dependencies: {', '.join(missing)}")
        if prompt_yes_no("Install dependencies using system package manager?", default=True):
            if not dep_manager.install_system_packages():
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

    # Create launcher
    create_launcher_script()

    # Create desktop entry
    create_desktop_entry()

    # Create autostart
    create_autostart_entry()

    # Create systemd service
    create_systemd_service()

    # Setup input group for Wayland
    setup_input_group()

    # Enable service
    enable_service()

    # Update desktop database
    update_desktop_database()

    # Done!
    print_header("Installation Complete!")
    print_success(f"{APP_DISPLAY_NAME} has been installed successfully!")
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


# ============================================================================
# Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_DISPLAY_NAME} Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python install.py install     Install SnipForge
    python install.py uninstall   Uninstall SnipForge
    python install.py status      Check installation status
"""
    )

    parser.add_argument(
        "action",
        nargs="?",
        default="install",
        choices=["install", "uninstall", "status"],
        help="Action to perform (default: install)"
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

    args = parser.parse_args()

    # Set global AUTO_YES flag
    global AUTO_YES
    AUTO_YES = args.yes

    # Check we're on Linux
    if sys.platform != "linux":
        print_error("This installer is for Linux only")
        print_info("Windows support coming soon!")
        sys.exit(1)

    # Run action
    try:
        if args.action == "install":
            success = install()
            sys.exit(0 if success else 1)
        elif args.action == "uninstall":
            uninstall()
        elif args.action == "status":
            check_status()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled")
        sys.exit(130)


if __name__ == "__main__":
    main()
