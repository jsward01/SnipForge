#!/usr/bin/env python3
"""
Build script for creating a self-contained SnipForge installer.

This script bundles snipforge.py, install.py, and all assets into a single
executable Python script that can be distributed and run standalone.

Usage:
    python build_installer.py

Output:
    snipforge_installer.py - Self-contained installer
"""

import base64
import os
import sys
from pathlib import Path
from datetime import datetime

# Files to bundle
SCRIPT_DIR = Path(__file__).parent.resolve()
FILES_TO_BUNDLE = {
    "snipforge.py": SCRIPT_DIR / "snipforge.py",
    "install.py": SCRIPT_DIR / "install.py",
    "SnipForge Icon.png": SCRIPT_DIR / "SnipForge Icon.png",
    "SnipForge App Icon.ico": SCRIPT_DIR / "SnipForge App Icon.ico",
    "SnipForge-Tray Icon.ico": SCRIPT_DIR / "SnipForge-Tray Icon.ico",
    "SnipForge Logo-black copy.png": SCRIPT_DIR / "SnipForge Logo-black copy.png",
    "SnipForge_Logo-white.png": SCRIPT_DIR / "SnipForge_Logo-white.png",
}

OUTPUT_FILE = SCRIPT_DIR / "snipforge_installer.py"

# Template for the self-contained installer
INSTALLER_TEMPLATE = '''#!/usr/bin/env python3
"""
SnipForge Self-Contained Installer
===================================

This is a self-contained installer that includes all necessary files.
Just run this script to install SnipForge.

Generated: {timestamp}
Version: {version}

Usage:
    python snipforge_installer.py [action] [options]

Actions:
    install     Install SnipForge (default)
    uninstall   Uninstall SnipForge
    status      Check installation status
    --help      Show all options
"""

import base64
import os
import sys
import tempfile
import shutil
from pathlib import Path

# Embedded files (base64 encoded)
EMBEDDED_FILES = {embedded_files}

def extract_files(dest_dir):
    """Extract embedded files to destination directory."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    for filename, data in EMBEDDED_FILES.items():
        filepath = dest / filename
        content = base64.b64decode(data)
        with open(filepath, 'wb') as f:
            f.write(content)
        # Make Python files executable
        if filename.endswith('.py'):
            filepath.chmod(0o755)

    return dest

def main():
    # Create temp directory for extracted files
    temp_dir = tempfile.mkdtemp(prefix="snipforge_install_")

    try:
        # Extract files silently
        extract_dir = extract_files(temp_dir)

        # Change to extracted directory so install.py can find source files
        original_cwd = os.getcwd()
        os.chdir(extract_dir)

        # Import and run the installer
        sys.path.insert(0, str(extract_dir))

        # Pass through command line arguments
        installer_path = extract_dir / "install.py"

        # Execute the installer
        import subprocess
        result = subprocess.run(
            [sys.executable, str(installer_path)] + sys.argv[1:],
            cwd=str(extract_dir)
        )

        os.chdir(original_cwd)
        sys.exit(result.returncode)

    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

if __name__ == "__main__":
    main()
'''

def get_version():
    """Extract version from snipforge.py"""
    import re
    with open(FILES_TO_BUNDLE["snipforge.py"], 'r') as f:
        content = f.read()
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    return match.group(1) if match else "unknown"

def build():
    """Build the self-contained installer."""
    print("Building self-contained SnipForge installer...")
    print("=" * 50)

    # Check all files exist
    for name, path in FILES_TO_BUNDLE.items():
        if not path.exists():
            print(f"ERROR: Missing file: {path}")
            return False
        print(f"  Found: {name}")

    # Encode files
    print("\nEncoding files...")
    encoded_files = {}
    total_size = 0

    for name, path in FILES_TO_BUNDLE.items():
        with open(path, 'rb') as f:
            content = f.read()
        encoded = base64.b64encode(content).decode('ascii')
        encoded_files[name] = encoded
        total_size += len(content)
        print(f"  {name}: {len(content):,} bytes")

    print(f"\nTotal uncompressed size: {total_size:,} bytes ({total_size/1024:.1f} KB)")

    # Generate installer
    print("\nGenerating installer...")

    # Format embedded files as Python dict literal
    files_str = "{\n"
    for name, encoded in encoded_files.items():
        # Split long strings for readability
        files_str += f'    "{name}": \n        "{encoded}",\n'
    files_str += "}"

    version = get_version()
    timestamp = datetime.now().isoformat()

    installer_content = INSTALLER_TEMPLATE.format(
        embedded_files=files_str,
        version=version,
        timestamp=timestamp
    )

    # Write installer
    with open(OUTPUT_FILE, 'w') as f:
        f.write(installer_content)

    OUTPUT_FILE.chmod(0o755)

    output_size = OUTPUT_FILE.stat().st_size
    print(f"\nCreated: {OUTPUT_FILE}")
    print(f"Size: {output_size:,} bytes ({output_size/1024:.1f} KB)")
    print(f"Version: {version}")
    print("\nDone! Distribute snipforge_installer.py to install SnipForge.")

    return True

if __name__ == "__main__":
    success = build()
    sys.exit(0 if success else 1)
