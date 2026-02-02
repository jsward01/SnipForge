#!/usr/bin/env python3
"""
SnipForge - A GUI-based text expansion tool for Linux and Windows
Requires: PyQt5, pynput, pyperclip, Pillow

Install (Windows):
    pip install PyQt5 pynput pyperclip Pillow pywin32

Install (Linux):
    pip install PyQt5 pynput pyperclip Pillow evdev
    # For Wayland support, add yourself to the 'input' group:
    sudo usermod -aG input $USER
    # Then log out and back in
"""

__version__ = "1.0.0"

import sys
import json
import os
import re
import socket
import platform
from datetime import datetime
from pathlib import Path

# Platform detection
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform.startswith('linux')
IS_MACOS = sys.platform == 'darwin'

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
                             QDialog, QLabel, QLineEdit, QTextEdit, QMessageBox,
                             QSystemTrayIcon, QMenu, QAction, QHeaderView, QInputDialog,
                             QComboBox, QCheckBox, QFileDialog, QGraphicsOpacityEffect,
                             QStackedWidget, QTreeWidget, QTreeWidgetItem, QAbstractItemView,
                             QCalendarWidget, QDialogButtonBox, QScrollArea, QFrame,
                             QSizePolicy, QDateEdit, QTabWidget, QSpinBox, QGroupBox,
                             QGridLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QPointF, QSharedMemory, QDate, QEvent, QObject
from PyQt5.QtGui import QIcon, QColor, QPixmap, QPainter, QPolygonF, QImage, QClipboard, QFont, QFontDatabase, QSyntaxHighlighter, QTextCharFormat
from pynput import keyboard
from pynput.keyboard import Key, Controller
import pyperclip
from PIL import Image
import io
import time
import subprocess
import shutil

# Linux-specific imports
if IS_LINUX:
    try:
        from evdev import InputDevice, ecodes, list_devices
        import selectors
        HAS_EVDEV = True
    except ImportError:
        HAS_EVDEV = False
        print("Warning: evdev not available. Using pynput for keyboard input.")
else:
    HAS_EVDEV = False

# Windows-specific imports
if IS_WINDOWS:
    try:
        import ctypes
        from ctypes import wintypes
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False


def get_config_dir():
    """Get the configuration directory based on platform."""
    if IS_WINDOWS:
        # Windows: %APPDATA%\SnipForge
        appdata = os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')
        return Path(appdata) / 'SnipForge'
    else:
        # Linux/macOS: ~/.config/snipforge
        return Path.home() / '.config' / 'snipforge'


def get_data_dir():
    """Get the data directory based on platform (for backups, etc.)."""
    if IS_WINDOWS:
        # Windows: %LOCALAPPDATA%\SnipForge
        localappdata = os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')
        return Path(localappdata) / 'SnipForge'
    else:
        # Linux/macOS: ~/.local/share/snipforge
        return Path.home() / '.local' / 'share' / 'snipforge'


class CustomToolTip(QLabel):
    """Custom tooltip widget with solid background to avoid compositor transparency"""
    _instance = None
    _timer = None

    @classmethod
    def showToolTip(cls, widget, text, pos):
        """Show a custom tooltip at the given position"""
        if not text:
            cls.hideToolTip()
            return

        if cls._instance is None:
            cls._instance = CustomToolTip()

        cls._instance.setText(text)
        cls._instance.adjustSize()

        # Position tooltip near the cursor
        cls._instance.move(pos.x() + 10, pos.y() + 20)
        cls._instance.show()
        cls._instance.raise_()

        # Auto-hide after 3 seconds
        if cls._timer is None:
            cls._timer = QTimer()
            cls._timer.setSingleShot(True)
            cls._timer.timeout.connect(cls.hideToolTip)
        cls._timer.start(3000)

    @classmethod
    def hideToolTip(cls):
        """Hide the custom tooltip"""
        if cls._instance:
            cls._instance.hide()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(True)

        # Set palette with solid colors
        from PyQt5.QtGui import QPalette, QColor
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor('#333333'))
        palette.setColor(QPalette.WindowText, QColor('#FFFFFF'))
        palette.setColor(QPalette.ToolTipBase, QColor('#333333'))
        palette.setColor(QPalette.ToolTipText, QColor('#FFFFFF'))
        self.setPalette(palette)

        self.setStyleSheet("""
            QLabel {
                background-color: #333333;
                color: #FFFFFF;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }
        """)


class ToolTipFilter(QObject):
    """Event filter to intercept tooltip events and show custom tooltips"""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ToolTip:
            # Get tooltip text
            tooltip = obj.toolTip() if hasattr(obj, 'toolTip') else ""
            if tooltip:
                # Show custom tooltip instead
                CustomToolTip.showToolTip(obj, tooltip, event.globalPos())
                return True  # Block the default tooltip
        elif event.type() == QEvent.Leave:
            # Hide tooltip when leaving widget
            CustomToolTip.hideToolTip()
        return False  # Let other events pass through


# Cross-platform keyboard controller (pynput)
_keyboard_controller = None

def get_keyboard_controller():
    """Get the pynput keyboard controller (lazy initialization)"""
    global _keyboard_controller
    if _keyboard_controller is None:
        _keyboard_controller = Controller()
    return _keyboard_controller


# Linux keycode to pynput Key mapping (for ydotool compatibility)
LINUX_KEYCODE_TO_PYNPUT = {
    1: Key.esc,           # Escape
    14: Key.backspace,    # Backspace
    28: Key.enter,        # Enter
    29: Key.ctrl_l,       # Left Ctrl
    42: Key.shift_l,      # Left Shift
    47: keyboard.KeyCode.from_char('v'),  # V key
    105: Key.left,        # Left arrow
    106: Key.right,       # Right arrow
    107: Key.end,         # End
}


def run_ydotool(cmd, *args):
    """Run ydotool command for Wayland keystroke injection (Linux only).
    On Windows, uses pynput keyboard controller instead."""
    if IS_WINDOWS:
        # Use pynput on Windows
        if cmd == 'key':
            return _pynput_key_from_ydotool_args(args)
        elif cmd == 'type':
            # Skip '--' argument
            text_args = [a for a in args if a != '--']
            if text_args:
                kb = get_keyboard_controller()
                kb.type(text_args[0])
            return True
        elif cmd == 'mousemove':
            return _pynput_mouse_move(args)
        elif cmd == 'click':
            return _pynput_mouse_click(args)
        return False
    else:
        # Use ydotool on Linux
        try:
            subprocess.run(['ydotool', cmd] + list(args), check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"ydotool error: {e.stderr.decode() if e.stderr else e}")
            return False
        except FileNotFoundError:
            print("ydotool not found - install with: sudo pacman -S ydotool")
            return False


def _pynput_key_from_ydotool_args(args):
    """Convert ydotool key arguments to pynput key presses"""
    kb = get_keyboard_controller()
    pressed_keys = []

    for arg in args:
        if ':' in arg:
            keycode_str, state = arg.split(':')
            keycode = int(keycode_str)
            key = LINUX_KEYCODE_TO_PYNPUT.get(keycode)

            if key:
                if state == '1':  # Press
                    kb.press(key)
                    pressed_keys.append(key)
                elif state == '0':  # Release
                    kb.release(key)
                    if key in pressed_keys:
                        pressed_keys.remove(key)

    # Make sure all keys are released
    for key in pressed_keys:
        kb.release(key)

    return True


def _pynput_mouse_move(args):
    """Move mouse using pynput (Windows)"""
    try:
        from pynput.mouse import Controller as MouseController
        mouse = MouseController()

        x, y = None, None
        i = 0
        while i < len(args):
            if args[i] == '-x' and i + 1 < len(args):
                x = int(args[i + 1])
                i += 2
            elif args[i] == '-y' and i + 1 < len(args):
                y = int(args[i + 1])
                i += 2
            elif args[i] == '--absolute':
                i += 1
            else:
                i += 1

        if x is not None and y is not None:
            mouse.position = (x, y)
            return True
    except Exception as e:
        print(f"Mouse move error: {e}")
    return False


def _pynput_mouse_click(args):
    """Click mouse using pynput (Windows)"""
    try:
        from pynput.mouse import Controller as MouseController, Button
        mouse = MouseController()
        mouse.click(Button.left, 1)
        return True
    except Exception as e:
        print(f"Mouse click error: {e}")
    return False


def ydotool_key(*keycodes):
    """Press keys using ydotool/pynput. Each keycode is pressed then released."""
    if IS_WINDOWS:
        # Use pynput on Windows
        kb = get_keyboard_controller()
        for kc in keycodes:
            key = LINUX_KEYCODE_TO_PYNPUT.get(kc)
            if key:
                kb.press(key)
                kb.release(key)
            else:
                print(f"Unknown keycode: {kc}")
        return True
    else:
        # Format: keycode:1 (press) keycode:0 (release)
        args = []
        for kc in keycodes:
            args.extend([f"{kc}:1", f"{kc}:0"])
        return run_ydotool('key', *args)


def ydotool_type(text):
    """Type text using ydotool/pynput"""
    if IS_WINDOWS:
        kb = get_keyboard_controller()
        kb.type(text)
        return True
    else:
        return run_ydotool('type', '--', text)


def press_ctrl_v():
    """Press Ctrl+V to paste (cross-platform)"""
    if IS_WINDOWS:
        kb = get_keyboard_controller()
        kb.press(Key.ctrl_l)
        kb.press(keyboard.KeyCode.from_char('v'))
        kb.release(keyboard.KeyCode.from_char('v'))
        kb.release(Key.ctrl_l)
        return True
    else:
        return run_ydotool('key', '29:1', '47:1', '47:0', '29:0')


class SnippetDialog(QDialog):
    """Dialog for creating/editing snippets"""
    
    def __init__(self, parent=None, snippet=None):
        super().__init__(parent)
        self.snippet = snippet or {}
        self.image_path = self.snippet.get('image_path', '')
        self.setWindowTitle("Edit Snippet" if snippet else "New Snippet")
        self.setMinimumSize(900, 600)
        self.init_ui()
        
    def init_ui(self):
        # Dark Forge theme for dialog
        self.setStyleSheet("""
            QDialog {
                background-color: #121212;
            }
            QWidget {
                font-family: 'Segoe UI', 'Roboto', 'Noto Sans', sans-serif;
                font-size: 14px;
                color: #E0E0E0;
            }
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: 500;
                min-height: 36px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
            QLineEdit, QTextEdit {
                background-color: rgba(30, 30, 30, 215);
                border: 1px solid #424242;
                border-radius: 4px;
                padding: 8px;
                color: #E0E0E0;
                selection-background-color: #3D2814;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 2px solid #FF6B00;
                padding: 7px;
            }
            QLabel {
                color: #E0E0E0;
            }
        """)

        main_layout = QHBoxLayout()
        main_layout.setSpacing(24)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # Left column - Main content
        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        
        # Trigger
        trigger_layout = QHBoxLayout()
        trigger_layout.addWidget(QLabel("Shortcut:"))
        self.trigger_input = QLineEdit(self.snippet.get('trigger', ''))
        self.trigger_input.setPlaceholderText("e.g., :email or /sig")
        trigger_layout.addWidget(self.trigger_input)
        left_column.addLayout(trigger_layout)
        
        # Description
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("Label:"))
        self.desc_input = QLineEdit(self.snippet.get('description', ''))
        self.desc_input.setPlaceholderText("Optional description")
        desc_layout.addWidget(self.desc_input)
        left_column.addLayout(desc_layout)
        
        # Content
        left_column.addWidget(QLabel("Content:"))
        self.content_input = QTextEdit()
        self.content_input.setPlainText(self.snippet.get('content', ''))
        left_column.addWidget(self.content_input)
        
        # Image section
        image_layout = QHBoxLayout()
        image_layout.addWidget(QLabel("Image:"))
        self.select_image_btn = QPushButton("Select Image")
        self.select_image_btn.clicked.connect(self.select_image)
        self.select_image_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #4A90D9;
                border: 2px solid #4A90D9;
            }
            QPushButton:hover {
                background-color: #1A2A3A;
            }
            QPushButton:pressed {
                background-color: #0A1A2A;
            }
        """)
        image_layout.addWidget(self.select_image_btn)

        self.clear_image_btn = QPushButton("Clear")
        self.clear_image_btn.clicked.connect(self.clear_image)
        self.clear_image_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #757575;
                border: 2px solid #424242;
            }
            QPushButton:hover {
                background-color: #252525;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #1E1E1E;
            }
        """)
        image_layout.addWidget(self.clear_image_btn)

        self.image_label = QLabel("No image selected" if not self.image_path else f"{Path(self.image_path).name}")
        self.image_label.setStyleSheet("QLabel { color: #757575; font-style: italic; padding-left: 8px; }")
        image_layout.addWidget(self.image_label)
        image_layout.addStretch()
        left_column.addLayout(image_layout)
        
        # Buttons at bottom
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        back_btn = QPushButton("Back")
        back_btn.clicked.connect(self.reject)
        back_btn.setMinimumWidth(100)
        back_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #B0B0B0;
                border: 2px solid #424242;
            }
            QPushButton:hover {
                background-color: #252525;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #1E1E1E;
            }
        """)
        button_layout.addWidget(back_btn)

        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setMinimumWidth(100)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #424242;
            }
            QPushButton:hover {
                background-color: #555555;
            }
            QPushButton:pressed {
                background-color: #333333;
            }
        """)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        save_btn.setMinimumWidth(100)

        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        left_column.addLayout(button_layout)
        
        # Right column - Insert commands
        right_column = QVBoxLayout()
        right_column.setSpacing(8)

        commands_header = QLabel("Dynamic Commands")
        commands_header.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: 600;
                color: #FF6B00;
                padding-bottom: 8px;
            }
        """)
        right_column.addWidget(commands_header)

        # Basic Commands section
        basic_label = QLabel("BASIC")
        basic_label.setStyleSheet("""
            QLabel {
                color: #757575;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 1px;
                margin-top: 8px;
            }
        """)
        right_column.addWidget(basic_label)

        # Command button style - warm colors inspired by the forge logo
        cmd_btn_style = """
            QPushButton {
                background-color: rgba(60, 40, 30, 180);
                color: #4A90D9;
                border: 1px solid rgba(255, 107, 0, 0.4);
                border-radius: 4px;
                text-align: left;
                padding-left: 12px;
            }
            QPushButton:hover {
                background-color: rgba(80, 50, 35, 200);
                border-color: #FF6B00;
                color: #5BA3E0;
            }
            QPushButton:pressed {
                background-color: rgba(100, 60, 40, 220);
            }
        """

        date_btn = QPushButton("  Date/Time")
        date_btn.setToolTip("Insert current date")
        date_btn.clicked.connect(lambda: self.show_datetime_menu())
        date_btn.setStyleSheet(cmd_btn_style)
        right_column.addWidget(date_btn)

        clipboard_btn = QPushButton("  Clipboard")
        clipboard_btn.setToolTip("Insert clipboard content")
        clipboard_btn.clicked.connect(lambda: self.insert_variable('{{clipboard}}'))
        clipboard_btn.setStyleSheet(cmd_btn_style)
        right_column.addWidget(clipboard_btn)

        cursor_btn = QPushButton("  Cursor Position")
        cursor_btn.setToolTip("Place cursor here after expansion")
        cursor_btn.clicked.connect(lambda: self.insert_variable('{{cursor}}'))
        cursor_btn.setStyleSheet(cmd_btn_style)
        right_column.addWidget(cursor_btn)
        
        # Forms section
        forms_label = QLabel("FORMS")
        forms_label.setStyleSheet("""
            QLabel {
                color: #757575;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 1px;
                margin-top: 16px;
            }
        """)
        right_column.addWidget(forms_label)
        
        text_field_btn = QPushButton("  Text Field")
        text_field_btn.setToolTip("Single line text input")
        text_field_btn.clicked.connect(self.insert_text_field_dialog)
        text_field_btn.setStyleSheet(cmd_btn_style)
        right_column.addWidget(text_field_btn)

        dropdown_btn = QPushButton("  Dropdown Menu")
        dropdown_btn.setToolTip("Multiple choice dropdown")
        dropdown_btn.clicked.connect(self.insert_dropdown_dialog)
        dropdown_btn.setStyleSheet(cmd_btn_style)
        right_column.addWidget(dropdown_btn)
        
        right_column.addStretch()
        
        # Help text at bottom
        help_text = QLabel("""<b>How to use:</b><br><br>
Click buttons to insert commands<br><br>
<b>Text fields:</b> {{name}} prompts for input<br><br>
<b>Dropdowns:</b> {{priority=Low|Medium|High}}<br><br>
Combine text, variables, forms, and images!""")
        help_text.setWordWrap(True)
        help_text.setStyleSheet("""
            QLabel {
                padding: 16px;
                background-color: rgba(50, 35, 25, 200);
                color: #C0C0C0;
                border-radius: 4px;
                border-left: 4px solid #FF6B00;
                font-size: 12px;
            }
        """)
        right_column.addWidget(help_text)
        
        # Add columns to main layout
        main_layout.addLayout(left_column, 3)
        main_layout.addLayout(right_column, 1)
        
        self.setLayout(main_layout)
    
    def insert_variable(self, variable):
        """Insert a variable at cursor position in content"""
        cursor = self.content_input.textCursor()
        cursor.insertText(variable)
        self.content_input.setFocus()

    def show_datetime_menu(self):
        """Show datetime format options"""
        items = ['{{date}} - Current date (YYYY-MM-DD)',
                 '{{time}} - Current time (HH:MM)',
                 '{{datetime}} - Date and time']
        item, ok = QInputDialog.getItem(self, 'Date/Time', 'Select format:', items, 0, False)
        if ok and item:
            variable = item.split(' - ')[0]
            self.insert_variable(variable)

    def insert_text_field_dialog(self):
        """Prompt for text field name and insert it"""
        name, ok = QInputDialog.getText(self, 'Text Field', 'Enter field name:')
        if ok and name:
            self.insert_variable('{{' + name.strip() + '}}')

    def insert_dropdown_dialog(self):
        """Prompt for dropdown field name and options"""
        name, ok = QInputDialog.getText(self, 'Dropdown Menu', 'Enter field name:')
        if ok and name:
            options, ok2 = QInputDialog.getText(self, 'Dropdown Options',
                                                 'Enter options separated by | (e.g., Low|Medium|High):')
            if ok2 and options:
                self.insert_variable('{{' + name.strip() + '=' + options.strip() + '}}')

    def get_file_dialog_stylesheet(self):
        """Get stylesheet for QFileDialog - always dark theme for legacy dialog"""
        return """
            QFileDialog, QDialog { background-color: #1E1E1E; }
            QWidget { background-color: #1E1E1E; color: #E0E0E0; }
            QFrame { background-color: #1E1E1E; }
            QTreeView, QListView, QTableView {
                background-color: #2A2A2A; color: #E0E0E0; border: 1px solid #424242;
            }
            QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {
                background-color: #3D2814; color: #FFFFFF;
            }
            QLineEdit {
                background-color: #2A2A2A; color: #E0E0E0;
                border: 1px solid #424242; border-radius: 4px; padding: 4px;
            }
            QPushButton {
                background-color: #FF6B00; color: white;
                border: none; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #FF8C00; }
            QComboBox {
                background-color: #2A2A2A; color: #E0E0E0;
                border: 1px solid #424242; border-radius: 4px; padding: 4px;
            }
            QHeaderView::section {
                background-color: #2A2A2A; color: #E0E0E0; border: none; padding: 4px;
            }
            QToolButton {
                background-color: #3D3D3D; border: 1px solid #424242;
                border-radius: 4px; padding: 4px;
            }
            QToolButton:hover { background-color: #4A4A4A; }
        """

    def select_image(self):
        """Open file dialog to select an image"""
        # Use same pattern as working get_text_input - main window as parent
        main_window = self.window()
        dialog = QFileDialog(main_window)
        dialog.setWindowTitle("Select Image")
        dialog.setDirectory(str(Path.home()))
        dialog.setNameFilter("Image Files (*.png *.jpg *.jpeg *.gif *.bmp);;All Files (*)")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setStyleSheet(self.get_file_dialog_stylesheet())

        if dialog.exec_() == QDialog.Accepted:
            files = dialog.selectedFiles()
            if files:
                file_path = files[0]
                self.image_path = file_path
                filename = Path(file_path).name
                self.image_label.setText(filename)
                self.image_label.setStyleSheet("QLabel { color: #FF6B00; font-style: normal; font-weight: 500; padding-left: 8px; }")
    
    def clear_image(self):
        """Clear the selected image"""
        self.image_path = ''
        self.image_label.setText("No image selected")
        self.image_label.setStyleSheet("QLabel { color: #757575; font-style: italic; padding-left: 8px; }")
    
    def get_snippet(self):
        """Return the snippet data"""
        snippet_data = {
            'trigger': self.trigger_input.text(),
            'description': self.desc_input.text(),
            'type': 'universal',  # All snippets are now universal
            'content': self.content_input.toPlainText(),
            'image_path': self.image_path if self.image_path else ''
        }
        return snippet_data


class SnippetFormDialog(QDialog):
    """Dialog for filling in snippet form fields before insertion"""

    def __init__(self, snippet, snippets_list=None, date_format='%m/%d/%Y', time_format='%I:%M %p', parent=None):
        super().__init__(parent)
        self.snippet = snippet
        self.snippets_list = snippets_list or []
        self.date_format = date_format
        self.time_format = time_format
        self.form_fields = {}  # Store references to form widgets
        self.result_content = None
        self.setWindowTitle(f"{snippet.get('trigger', '')} - {snippet.get('description', 'Snippet')}")
        self.setMinimumSize(650, 450)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1E1E1E;
            }
            QLabel {
                color: #E0E0E0;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Title bar
        title_bar = QWidget()
        title_bar.setStyleSheet("background-color: #2D4A5E;")
        title_bar.setFixedHeight(40)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)

        title_label = QLabel(f"{self.snippet.get('trigger', '')} – {self.snippet.get('description', 'Snippet')}")
        title_label.setStyleSheet("color: white; font-weight: 500; font-size: 14px;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        main_layout.addWidget(title_bar)

        # Scroll area for form content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #FAFAFA;
            }
        """)

        # Form content widget
        form_widget = QWidget()
        form_widget.setStyleSheet("background-color: #FAFAFA;")
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(20, 20, 20, 20)
        form_layout.setSpacing(4)

        # Build the form content
        self.build_form_content(form_layout, self.snippet.get('content', ''))

        form_layout.addStretch()
        scroll.setWidget(form_widget)
        main_layout.addWidget(scroll)

        # Button bar
        button_bar = QWidget()
        button_bar.setStyleSheet("background-color: #F5F5F5; border-top: 1px solid #E0E0E0;")
        button_bar.setFixedHeight(60)
        button_layout = QHBoxLayout(button_bar)
        button_layout.setContentsMargins(20, 10, 20, 10)

        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #00ACC1;
                border: none;
                padding: 10px 24px;
                font-weight: 500;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #E0F7FA;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(cancel_btn)

        insert_btn = QPushButton("Insert")
        insert_btn.clicked.connect(self.on_insert)
        insert_btn.setDefault(True)  # Enter key triggers this button
        insert_btn.setAutoDefault(True)
        insert_btn.setStyleSheet("""
            QPushButton {
                background-color: #00ACC1;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 24px;
                font-weight: 500;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #00BCD4;
            }
        """)
        button_layout.addWidget(insert_btn)

        main_layout.addWidget(button_bar)

        # Focus first text field and connect Enter key for all text fields
        self.first_text_field = None
        for field_id, field_data in self.form_fields.items():
            if field_data['type'] == 'text':
                widget = field_data['widget']
                # Connect Enter key to insert
                widget.returnPressed.connect(self.on_insert)
                # Connect text changes to update calculations in real-time
                widget.textChanged.connect(self.update_calculations)
                # Remember first text field for focus
                if self.first_text_field is None:
                    self.first_text_field = widget

        # Initial calculation update
        self.update_calculations()

    def update_calculations(self):
        """Update all calculation fields in real-time based on current input values"""
        import re
        import math

        # Gather current field values
        field_values = {}
        for field_id, field_data in self.form_fields.items():
            if field_data['type'] == 'text':
                field_name = field_data.get('name', '')
                if field_name:
                    field_values[field_name] = field_data['widget'].text()

        # Safe math functions
        safe_funcs = {
            'round': round, 'floor': math.floor, 'ceil': math.ceil,
            'abs': abs, 'min': min, 'max': max, 'pow': pow, 'sqrt': math.sqrt,
        }

        # Update each calc field
        for field_id, field_data in self.form_fields.items():
            if field_data['type'] == 'calc':
                expr = field_data.get('expr', '')
                label = field_data['widget']

                try:
                    # Replace field references with their values
                    eval_expr = expr
                    has_all_values = True
                    for field_name, value in field_values.items():
                        if field_name in eval_expr:
                            try:
                                num_value = float(value) if value else 0
                                if not value:  # Empty field
                                    has_all_values = False
                            except (ValueError, TypeError):
                                num_value = 0
                                has_all_values = False
                            eval_expr = re.sub(r'\b' + re.escape(field_name) + r'\b', str(num_value), eval_expr)

                    # Check for any remaining variables
                    remaining_words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', eval_expr)
                    for word in remaining_words:
                        if word not in safe_funcs:
                            has_all_values = False
                            eval_expr = re.sub(r'\b' + re.escape(word) + r'\b', '0', eval_expr)

                    # Evaluate
                    result = eval(eval_expr, {"__builtins__": {}}, safe_funcs)
                    if isinstance(result, float):
                        if result == int(result):
                            result = int(result)
                        else:
                            result = round(result, 2)

                    # Show result (grayed if not all values entered)
                    if has_all_values:
                        label.setText(f"= {result}")
                        label.setStyleSheet("""
                            QLabel {
                                background-color: #E8F5E9;
                                color: #2E7D32;
                                border: 1px solid #A5D6A7;
                                border-radius: 3px;
                                padding: 4px 8px;
                                font-family: monospace;
                                font-weight: bold;
                            }
                        """)
                    else:
                        label.setText(f"= {result}")
                        label.setStyleSheet("""
                            QLabel {
                                background-color: #FFF3E0;
                                color: #E65100;
                                border: 1px solid #FFB74D;
                                border-radius: 3px;
                                padding: 4px 8px;
                                font-family: monospace;
                                font-weight: 500;
                            }
                        """)
                except:
                    # Show original expression on error
                    label.setText(f"= {expr}")
                    label.setStyleSheet("""
                        QLabel {
                            background-color: #FFF3E0;
                            color: #E65100;
                            border: 1px solid #FFB74D;
                            border-radius: 3px;
                            padding: 4px 8px;
                            font-family: monospace;
                            font-weight: 500;
                        }
                    """)

    def showEvent(self, event):
        """Set focus to first text field when dialog becomes visible"""
        super().showEvent(event)
        if hasattr(self, 'first_text_field') and self.first_text_field:
            # Use QTimer to set focus after event loop processes the show
            QTimer.singleShot(50, self.first_text_field.setFocus)

    def build_form_content(self, layout, content):
        """Build form content with inline editable fields"""
        import re

        # First expand any nested snippets
        snippet_pattern = r'\{\{snippet:([^}]+)\}\}'
        snippet_matches = re.findall(snippet_pattern, content)
        for trigger in snippet_matches:
            trigger = trigger.strip()
            nested_content = ''
            for s in self.snippets_list:
                if s.get('trigger', '') == trigger:
                    nested_content = s.get('content', '')
                    break
            content = content.replace('{{snippet:' + trigger + '}}', nested_content)

        # Process toggle sections first - these can span multiple lines
        # Syntax: {{name:toggle}}content{{/name:toggle}}
        self.toggle_sections = {}  # Store toggle checkboxes and their content containers
        self.field_counter = 0

        # Parse and build content with toggle sections
        self._build_content_recursive(layout, content)

    def _build_content_recursive(self, layout, content):
        """Recursively build content, handling toggle sections"""
        import re

        # Pattern for toggle sections: {{name:toggle}}...{{/name:toggle}}
        toggle_pattern = r'\{\{([^}:]+):toggle\}\}(.*?)\{\{/\1:toggle\}\}'

        # Find the first toggle section
        match = re.search(toggle_pattern, content, re.DOTALL)

        if match:
            # Content before the toggle
            before_content = content[:match.start()]
            if before_content:
                self._build_lines(layout, before_content)

            # The toggle section
            toggle_name = match.group(1).strip()
            toggle_content = match.group(2)
            toggle_full_match = match.group(0)

            # Create toggle section UI
            self._create_toggle_section(layout, toggle_name, toggle_content, toggle_full_match)

            # Content after the toggle
            after_content = content[match.end():]
            if after_content:
                self._build_content_recursive(layout, after_content)
        else:
            # No more toggle sections, just build the remaining content
            self._build_lines(layout, content)

    def _create_toggle_section(self, layout, toggle_name, toggle_content, full_match):
        """Create a toggle section with checkbox and content container"""
        # Create container for the toggle section
        toggle_container = QWidget()
        toggle_container.setStyleSheet("background: transparent;")
        toggle_layout = QVBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(0, 4, 0, 4)
        toggle_layout.setSpacing(2)

        # Create checkbox row
        checkbox_row = QWidget()
        checkbox_row.setStyleSheet("background: transparent;")
        checkbox_layout = QHBoxLayout(checkbox_row)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setSpacing(8)

        checkbox = QCheckBox(toggle_name)
        checkbox.setChecked(True)  # Default to checked
        checkbox.setStyleSheet("""
            QCheckBox {
                color: #333333;
                font-weight: 500;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #00ACC1;
                border-radius: 3px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: #00ACC1;
            }
        """)
        checkbox_layout.addWidget(checkbox)
        checkbox_layout.addStretch()
        toggle_layout.addWidget(checkbox_row)

        # Create content container (indented)
        content_container = QWidget()
        content_container.setStyleSheet("background: transparent; margin-left: 26px;")
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(26, 0, 0, 0)
        content_layout.setSpacing(2)

        # Build the content inside the toggle
        self._build_lines(content_layout, toggle_content)

        toggle_layout.addWidget(content_container)

        # Connect checkbox to show/hide content
        def toggle_visibility(checked):
            content_container.setVisible(checked)
            # Update opacity to show it's disabled
            if checked:
                content_container.setStyleSheet("background: transparent; margin-left: 26px;")
            else:
                content_container.setStyleSheet("background: transparent; margin-left: 26px; opacity: 0.4;")

        checkbox.toggled.connect(toggle_visibility)

        # Store toggle info for processing on insert
        field_id = f"field_{self.field_counter}"
        self.form_fields[field_id] = {
            'type': 'toggle_section',
            'widget': checkbox,
            'content_widget': content_container,
            'match': full_match,
            'inner_content': toggle_content,
            'name': toggle_name
        }
        self.field_counter += 1

        layout.addWidget(toggle_container)

    def _build_lines(self, layout, content):
        """Build content lines with inline form fields"""
        import re

        # Define patterns for different variable types (excluding toggle sections)
        patterns = [
            (r'\{\{calc:([^}]+)\}\}', 'calc'),  # Calculation expression
            (r'\{\{([^}:]+):multi=([^}]+)\}\}', 'multi'),
            (r'\{\{([^}:]+):date\}\}', 'date_picker'),  # Date picker field
            (r'\{\{date([+-])(\d+)\}\}', 'date_arith'),  # Date arithmetic
            (r'\{\{(date)\}\}', 'date_var'),
            (r'\{\{(time)\}\}', 'time_var'),
            (r'\{\{(datetime)\}\}', 'datetime_var'),
            (r'\{\{(clipboard)\}\}', 'clipboard_var'),
            (r'\{\{(cursor)\}\}', 'cursor_var'),
            (r'\{\{([^}=:]+)=([^}]+)\}\}', 'dropdown'),
            (r'\{\{([^}=:/]+)\}\}', 'text'),  # Exclude / to not match closing toggle tags
        ]

        # Split content into lines
        lines = content.split('\n')

        for line in lines:
            line_widget = QWidget()
            line_widget.setStyleSheet("background: transparent;")
            line_layout = QHBoxLayout(line_widget)
            line_layout.setContentsMargins(0, 2, 0, 2)
            line_layout.setSpacing(0)

            remaining = line
            while remaining:
                earliest_match = None
                earliest_pos = len(remaining)
                match_type = None
                match_groups = None
                match_full = None

                for pattern, var_type in patterns:
                    match = re.search(pattern, remaining)
                    if match and match.start() < earliest_pos:
                        earliest_match = match
                        earliest_pos = match.start()
                        match_type = var_type
                        match_groups = match.groups()
                        match_full = match.group(0)

                if earliest_match:
                    # Add text before match
                    if earliest_pos > 0:
                        text_label = QLabel(remaining[:earliest_pos])
                        text_label.setStyleSheet("color: #333333; background: transparent;")
                        line_layout.addWidget(text_label)

                    # Create form field
                    field_id = f"field_{self.field_counter}"
                    field_widget = self.create_form_field(field_id, match_type, match_groups, match_full)
                    line_layout.addWidget(field_widget)
                    self.field_counter += 1

                    remaining = remaining[earliest_match.end():]
                else:
                    if remaining:
                        text_label = QLabel(remaining)
                        text_label.setStyleSheet("color: #333333; background: transparent;")
                        line_layout.addWidget(text_label)
                    remaining = ""

            line_layout.addStretch()
            layout.addWidget(line_widget)

    def create_form_field(self, field_id, field_type, groups, full_match):
        """Create an editable form field widget"""
        if field_type == 'text':
            name = groups[0]
            field = QLineEdit()
            field.setPlaceholderText(name)
            field.setStyleSheet("""
                QLineEdit {
                    background-color: #FFFDE7;
                    color: #BF360C;
                    border: 1px solid #FFE082;
                    border-radius: 3px;
                    padding: 4px 8px;
                    min-width: 150px;
                }
                QLineEdit:focus {
                    border: 2px solid #FFA000;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': field, 'match': full_match, 'name': name}
            return field

        elif field_type == 'dropdown':
            name, options = groups
            combo = QComboBox()
            combo.addItems([opt.strip() for opt in options.split('|')])
            combo.setStyleSheet("""
                QComboBox {
                    background-color: #FFFDE7;
                    color: #333333;
                    border: 1px solid #FFE082;
                    border-radius: 3px;
                    padding: 4px 24px 4px 8px;
                    min-width: 120px;
                }
                QComboBox::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 20px;
                    border-left: 1px solid #FFE082;
                    background-color: #FFF8E1;
                }
                QComboBox::down-arrow {
                    width: 0;
                    height: 0;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 6px solid #666666;
                }
                QComboBox QAbstractItemView {
                    background-color: white;
                    color: #333333;
                    selection-background-color: #FFE082;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': combo, 'match': full_match}
            return combo

        elif field_type == 'multi':
            name, options = groups
            container = QWidget()
            container.setStyleSheet("background: transparent;")
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(12)
            checkboxes = []
            for opt in options.split('|'):
                cb = QCheckBox(opt.strip())
                cb.setStyleSheet("""
                    QCheckBox {
                        color: #333333;
                        spacing: 4px;
                    }
                    QCheckBox::indicator {
                        width: 16px;
                        height: 16px;
                        border: 2px solid #00ACC1;
                        border-radius: 3px;
                        background-color: white;
                    }
                    QCheckBox::indicator:checked {
                        background-color: #00ACC1;
                    }
                """)
                checkboxes.append(cb)
                container_layout.addWidget(cb)
            self.form_fields[field_id] = {'type': field_type, 'widget': checkboxes, 'match': full_match}
            return container

        elif field_type == 'date_picker':
            name = groups[0]
            date_edit = QDateEdit()
            date_edit.setDate(QDate.currentDate())
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("MM/dd/yyyy")
            date_edit.setStyleSheet("""
                QDateEdit {
                    background-color: #FFFDE7;
                    color: #333333;
                    border: 1px solid #FFE082;
                    border-radius: 3px;
                    padding: 4px 8px;
                    min-width: 120px;
                }
                QDateEdit::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 20px;
                    border-left: 1px solid #FFE082;
                    background-color: #FFF8E1;
                }
                QDateEdit::down-arrow {
                    width: 0;
                    height: 0;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 6px solid #666666;
                }
                QCalendarWidget {
                    background-color: white;
                }
                QCalendarWidget QToolButton {
                    color: #333333;
                    background-color: #E3F2FD;
                    border-radius: 3px;
                    padding: 4px;
                }
                QCalendarWidget QMenu {
                    background-color: white;
                    color: #333333;
                }
                QCalendarWidget QSpinBox {
                    background-color: white;
                    color: #333333;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': date_edit, 'match': full_match, 'name': name}
            return date_edit

        elif field_type == 'date_arith':
            from datetime import timedelta
            operator, days = groups
            days = int(days)
            if operator == '-':
                days = -days
            result_date = datetime.now() + timedelta(days=days)
            label = QLabel(result_date.strftime(self.date_format))
            label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    border: 1px solid #64B5F6;
                    border-radius: 3px;
                    padding: 4px 8px;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': label, 'match': full_match}
            return label

        elif field_type == 'date_var':
            label = QLabel(datetime.now().strftime(self.date_format))
            label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    border: 1px solid #64B5F6;
                    border-radius: 3px;
                    padding: 4px 8px;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': label, 'match': full_match}
            return label

        elif field_type == 'time_var':
            label = QLabel(datetime.now().strftime(self.time_format_getter()))
            label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    border: 1px solid #64B5F6;
                    border-radius: 3px;
                    padding: 4px 8px;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': label, 'match': full_match}
            return label

        elif field_type == 'datetime_var':
            label = QLabel(datetime.now().strftime(self.date_format + ' ' + self.time_format_getter()))
            label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    border: 1px solid #64B5F6;
                    border-radius: 3px;
                    padding: 4px 8px;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': label, 'match': full_match}
            return label

        elif field_type == 'clipboard_var':
            try:
                clipboard_text = pyperclip.paste()[:30] + "..." if len(pyperclip.paste()) > 30 else pyperclip.paste()
            except:
                clipboard_text = "(clipboard)"
            label = QLabel(f"[{clipboard_text}]")
            label.setStyleSheet("""
                QLabel {
                    background-color: #F3E5F5;
                    color: #7B1FA2;
                    border: 1px solid #CE93D8;
                    border-radius: 3px;
                    padding: 4px 8px;
                    font-size: 11px;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': label, 'match': full_match}
            return label

        elif field_type == 'cursor_var':
            label = QLabel("CURSOR")
            label.setStyleSheet("""
                QLabel {
                    background-color: #E8F5E9;
                    color: #2E7D32;
                    border: 1px solid #A5D6A7;
                    border-radius: 3px;
                    padding: 4px 8px;
                    font-size: 11px;
                    font-weight: 500;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': label, 'match': full_match}
            return label

        elif field_type == 'calc':
            expr = groups[0]
            label = QLabel(f"= {expr}")
            label.setStyleSheet("""
                QLabel {
                    background-color: #FFF3E0;
                    color: #E65100;
                    border: 1px solid #FFB74D;
                    border-radius: 3px;
                    padding: 4px 8px;
                    font-family: monospace;
                    font-weight: 500;
                }
            """)
            self.form_fields[field_id] = {'type': field_type, 'widget': label, 'match': full_match, 'expr': expr}
            return label

        return QLabel("")

    def on_insert(self):
        """Collect form values and generate final content"""
        try:
            content = self.snippet.get('content', '')
            field_values = {}  # Track field values for calculations

            # First expand nested snippets
            import re
            import math
            snippet_pattern = r'\{\{snippet:([^}]+)\}\}'
            snippet_matches = re.findall(snippet_pattern, content)
            for trigger in snippet_matches:
                trigger = trigger.strip()
                nested_content = ''
                for s in self.snippets_list:
                    if s.get('trigger', '') == trigger:
                        nested_content = s.get('content', '')
                        break
                content = content.replace('{{snippet:' + trigger + '}}', nested_content)

            # Process toggle sections first (they contain other fields)
            for field_id, field_data in self.form_fields.items():
                if field_data['type'] == 'toggle_section':
                    checkbox = field_data['widget']
                    match = field_data['match']
                    inner_content = field_data['inner_content']

                    if checkbox.isChecked():
                        # Keep the inner content, remove the toggle tags
                        content = content.replace(match, inner_content, 1)
                    else:
                        # Remove the entire toggle section
                        content = content.replace(match, '', 1)

            # Replace form fields with their values
            for field_id, field_data in self.form_fields.items():
                field_type = field_data['type']
                widget = field_data['widget']
                match = field_data['match']

                if field_type == 'toggle_section':
                    # Already processed above
                    continue

                if field_type == 'calc':
                    # Calculations are processed separately below
                    continue

                if field_type == 'text':
                    value = widget.text() or ''
                    field_name = field_data.get('name', '')
                    if field_name:
                        field_values[field_name] = value
                    content = content.replace(match, value, 1)

                elif field_type == 'dropdown':
                    value = widget.currentText()
                    content = content.replace(match, value, 1)

                elif field_type == 'multi':
                    selected = [cb.text() for cb in widget if cb.isChecked()]
                    value = ', '.join(selected)
                    content = content.replace(match, value, 1)

                elif field_type == 'date_picker':
                    value = widget.date().toString('MM/dd/yyyy')
                    field_name = field_data.get('name', '')
                    if field_name:
                        field_values[field_name] = value
                    content = content.replace(match, value, 1)

                elif field_type == 'date_arith':
                    from datetime import timedelta
                    # The value is already computed in create_form_field
                    value = widget.text()
                    content = content.replace(match, value, 1)

                elif field_type == 'date_var':
                    value = datetime.now().strftime(self.date_format)
                    content = content.replace(match, value, 1)

                elif field_type == 'time_var':
                    value = datetime.now().strftime(self.time_format)
                    content = content.replace(match, value, 1)

                elif field_type == 'datetime_var':
                    value = datetime.now().strftime(self.date_format + ' ' + self.time_format)
                    content = content.replace(match, value, 1)

                elif field_type == 'clipboard_var':
                    try:
                        value = pyperclip.paste()
                    except:
                        value = ''
                    content = content.replace(match, value, 1)

                elif field_type == 'cursor_var':
                    # Remove cursor marker for now (cursor positioning is complex)
                    content = content.replace(match, '', 1)

            # Process calculations: {{calc:expression}}
            calc_pattern = r'\{\{calc:([^}]+)\}\}'
            calc_matches = re.findall(calc_pattern, content)
            for expr in calc_matches:
                original_expr = expr
                try:
                    # Replace field references with their values
                    for field_name, value in field_values.items():
                        try:
                            num_value = float(value) if value else 0
                        except (ValueError, TypeError):
                            num_value = 0
                        expr = re.sub(r'\b' + re.escape(field_name) + r'\b', str(num_value), expr)

                    # Safe math functions
                    safe_funcs = {
                        'round': round, 'floor': math.floor, 'ceil': math.ceil,
                        'abs': abs, 'min': min, 'max': max, 'pow': pow, 'sqrt': math.sqrt,
                    }

                    # Replace unknown variables with 0
                    remaining_words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', expr)
                    for word in remaining_words:
                        if word not in safe_funcs:
                            expr = re.sub(r'\b' + re.escape(word) + r'\b', '0', expr)

                    # Evaluate
                    result = eval(expr, {"__builtins__": {}}, safe_funcs)
                    if isinstance(result, float):
                        if result == int(result):
                            result = int(result)
                        else:
                            result = round(result, 2)

                    content = content.replace('{{calc:' + original_expr + '}}', str(result), 1)
                except:
                    content = content.replace('{{calc:' + original_expr + '}}', '[calc error]', 1)

            self.result_content = content
            self.accept()
        except:
            self.result_content = None
            self.reject()

    def get_result(self):
        """Return the processed content"""
        return self.result_content


class TutorialDialog(QDialog):
    """First-run tutorial wizard to help new users get started"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Welcome to SnipForge")
        self.setMinimumSize(500, 400)
        self.setMaximumSize(600, 500)
        self.current_step = 0
        self.dont_show_again = False
        self.tutorial_snippet_trigger = ":h"
        self.tutorial_snippet_content = "Hello!"
        self.snippet_created = False
        self.trigger_detected_count = 0

        # Detect current theme from parent window
        self.is_light_theme = False
        if parent and hasattr(parent, 'current_theme'):
            self.is_light_theme = (parent.current_theme == 'Light')

        self.init_ui()
        self.show_step(0)

    def get_dark_stylesheet(self):
        """Return dark theme stylesheet for tutorial dialog"""
        return """
            QDialog {
                background-color: #1E1E1E;
            }
            QLabel {
                color: #E0E0E0;
                font-size: 14px;
            }
            QLabel#stepLabel {
                color: #888888;
                font-size: 12px;
            }
            QLabel#titleLabel {
                color: #FF6B00;
                font-size: 20px;
                font-weight: bold;
            }
            QLabel#descLabel {
                color: #CCCCCC;
                font-size: 14px;
                line-height: 1.5;
            }
            QLabel#successLabel {
                color: #4CAF50;
                font-size: 16px;
                font-weight: bold;
            }
            QLabel#waitingLabel {
                color: #FF6B00;
                font-size: 14px;
            }
            QLineEdit {
                background-color: #2A2A2A;
                color: #E0E0E0;
                border: 1px solid #424242;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #FF6B00;
            }
            QCheckBox {
                color: #E0E0E0;
                spacing: 8px;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #424242;
                border-radius: 3px;
                background-color: #2A2A2A;
            }
            QCheckBox::indicator:checked {
                background-color: #FF6B00;
                border-color: #FF6B00;
            }
            QCheckBox::indicator:hover {
                border-color: #FF6B00;
            }
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 24px;
                font-weight: 500;
                font-size: 14px;
                min-height: 36px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
            QPushButton#skipBtn {
                background-color: transparent;
                color: #888888;
                border: none;
            }
            QPushButton#skipBtn:hover {
                color: #E0E0E0;
            }
            QPushButton#backBtn {
                background-color: transparent;
                color: #888888;
                border: 1px solid #424242;
            }
            QPushButton#backBtn:hover {
                color: #E0E0E0;
                border-color: #666666;
            }
        """

    def get_light_stylesheet(self):
        """Return light theme stylesheet for tutorial dialog"""
        return """
            QDialog {
                background-color: #F5F5F5;
            }
            QLabel {
                color: #212121;
                font-size: 14px;
            }
            QLabel#stepLabel {
                color: #757575;
                font-size: 12px;
            }
            QLabel#titleLabel {
                color: #E65100;
                font-size: 20px;
                font-weight: bold;
            }
            QLabel#descLabel {
                color: #424242;
                font-size: 14px;
                line-height: 1.5;
            }
            QLabel#successLabel {
                color: #2E7D32;
                font-size: 16px;
                font-weight: bold;
            }
            QLabel#waitingLabel {
                color: #E65100;
                font-size: 14px;
            }
            QLineEdit {
                background-color: #FFFFFF;
                color: #212121;
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #FF6B00;
            }
            QCheckBox {
                color: #212121;
                spacing: 8px;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #BDBDBD;
                border-radius: 3px;
                background-color: #FFFFFF;
            }
            QCheckBox::indicator:checked {
                background-color: #FF6B00;
                border-color: #FF6B00;
            }
            QCheckBox::indicator:hover {
                border-color: #FF6B00;
            }
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 24px;
                font-weight: 500;
                font-size: 14px;
                min-height: 36px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
            QPushButton#skipBtn {
                background-color: transparent;
                color: #757575;
                border: none;
            }
            QPushButton#skipBtn:hover {
                color: #424242;
            }
            QPushButton#backBtn {
                background-color: transparent;
                color: #757575;
                border: 1px solid #BDBDBD;
            }
            QPushButton#backBtn:hover {
                color: #424242;
                border-color: #9E9E9E;
            }
        """

    def init_ui(self):
        """Initialize the tutorial dialog UI"""
        if self.is_light_theme:
            self.setStyleSheet(self.get_light_stylesheet())
        else:
            self.setStyleSheet(self.get_dark_stylesheet())

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Step indicator at top
        self.step_label = QLabel("Step 1 of 4")
        self.step_label.setObjectName("stepLabel")
        self.step_label.setAlignment(Qt.AlignRight)
        main_layout.addWidget(self.step_label)

        # Content area (will be updated per step)
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(16)
        main_layout.addWidget(self.content_widget, 1)

        # Bottom area with checkbox and buttons
        bottom_layout = QVBoxLayout()
        bottom_layout.setSpacing(16)

        # Don't show again checkbox (only visible on step 0)
        self.dont_show_checkbox = QCheckBox("Don't show this tutorial again")
        self.dont_show_checkbox.stateChanged.connect(self.on_dont_show_changed)
        bottom_layout.addWidget(self.dont_show_checkbox)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        self.skip_btn = QPushButton("Skip Tutorial")
        self.skip_btn.setObjectName("skipBtn")
        self.skip_btn.clicked.connect(self.on_skip)
        button_layout.addWidget(self.skip_btn)

        button_layout.addStretch()

        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("backBtn")
        self.back_btn.clicked.connect(self.on_back)
        button_layout.addWidget(self.back_btn)

        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.on_next)
        button_layout.addWidget(self.next_btn)

        bottom_layout.addLayout(button_layout)
        main_layout.addLayout(bottom_layout)

    def clear_content(self):
        """Clear all widgets from content area"""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_step(self, step):
        """Display the content for a specific step"""
        self.current_step = step
        self.clear_content()

        # Update step indicator
        self.step_label.setText(f"Step {step + 1} of 4")

        # Show/hide checkbox only on first step
        self.dont_show_checkbox.setVisible(step == 0)

        # Show/hide back button
        self.back_btn.setVisible(step > 0)

        # Update button text
        if step == 3:
            self.next_btn.setText("Finish")
        else:
            self.next_btn.setText("Next")

        if step == 0:
            self.show_welcome_step()
        elif step == 1:
            self.show_create_step()
        elif step == 2:
            self.show_test_step()
        elif step == 3:
            self.show_complete_step()

    def show_welcome_step(self):
        """Step 1: Welcome and explain tray icon"""
        title = QLabel("Welcome to SnipForge!")
        title.setObjectName("titleLabel")
        self.content_layout.addWidget(title)

        # Tray icon illustration
        tray_widget = QWidget()
        tray_layout = QHBoxLayout(tray_widget)
        tray_layout.setContentsMargins(0, 20, 0, 20)

        # Create a visual representation of tray area
        tray_visual = QLabel()
        tray_visual.setFixedSize(200, 60)
        if self.is_light_theme:
            tray_visual.setStyleSheet("""
                background-color: #E0E0E0;
                border-radius: 8px;
                border: 2px solid #BDBDBD;
            """)
        else:
            tray_visual.setStyleSheet("""
                background-color: #2A2A2A;
                border-radius: 8px;
                border: 2px solid #424242;
            """)

        # Add tray icon indicator inside
        inner_layout = QHBoxLayout(tray_visual)
        inner_layout.setContentsMargins(8, 8, 8, 8)
        inner_layout.addStretch()

        # Load actual tray icon if available
        tray_icon_path = get_config_dir() / 'tray_icon.ico'
        if tray_icon_path.exists():
            icon_label = QLabel()
            pixmap = QPixmap(str(tray_icon_path))
            if not pixmap.isNull():
                icon_label.setPixmap(pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                inner_layout.addWidget(icon_label)
        else:
            # Fallback: show text indicator
            icon_label = QLabel("🔧")
            icon_label.setStyleSheet("font-size: 24px;")
            inner_layout.addWidget(icon_label)

        # Arrow pointing to icon
        arrow_label = QLabel("←")
        arrow_label.setStyleSheet("font-size: 24px; color: #FF6B00; font-weight: bold;")
        inner_layout.addWidget(arrow_label)

        inner_layout.addSpacing(20)

        tray_layout.addStretch()
        tray_layout.addWidget(tray_visual)
        tray_layout.addStretch()
        self.content_layout.addWidget(tray_widget)

        # Description
        desc = QLabel(
            "SnipForge runs in your system tray (the area near your clock).\n\n"
            "Click the tray icon anytime to open the main window and manage your snippets.\n\n"
            "Snippets are text shortcuts - type a trigger (like ':h') and it automatically "
            "expands to your saved content."
        )
        desc.setObjectName("descLabel")
        desc.setWordWrap(True)
        self.content_layout.addWidget(desc)

        self.content_layout.addStretch()

    def show_create_step(self):
        """Step 2: Create first snippet"""
        title = QLabel("Create Your First Snippet")
        title.setObjectName("titleLabel")
        self.content_layout.addWidget(title)

        desc = QLabel(
            "A snippet has two parts:\n"
            "  • Trigger - what you type (e.g., ':h')\n"
            "  • Content - what it expands to (e.g., 'Hello!')\n\n"
            "Let's create a simple one to try it out:"
        )
        desc.setObjectName("descLabel")
        desc.setWordWrap(True)
        self.content_layout.addWidget(desc)

        # Form for trigger and content
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(0, 16, 0, 16)
        form_layout.setSpacing(12)

        # Trigger input
        trigger_row = QHBoxLayout()
        trigger_label = QLabel("Trigger:")
        trigger_label.setFixedWidth(80)
        self.trigger_input = QLineEdit()
        self.trigger_input.setText(self.tutorial_snippet_trigger)
        self.trigger_input.setPlaceholderText(":h")
        self.trigger_input.setMaximumWidth(150)
        trigger_row.addWidget(trigger_label)
        trigger_row.addWidget(self.trigger_input)
        trigger_row.addStretch()
        form_layout.addLayout(trigger_row)

        # Content input
        content_row = QHBoxLayout()
        content_label = QLabel("Content:")
        content_label.setFixedWidth(80)
        self.content_input = QLineEdit()
        self.content_input.setText(self.tutorial_snippet_content)
        self.content_input.setPlaceholderText("Hello!")
        self.content_input.setMaximumWidth(300)
        content_row.addWidget(content_label)
        content_row.addWidget(self.content_input)
        content_row.addStretch()
        form_layout.addLayout(content_row)

        self.content_layout.addWidget(form_widget)

        # Status label for snippet creation
        self.create_status_label = QLabel("")
        self.create_status_label.setObjectName("successLabel")
        self.content_layout.addWidget(self.create_status_label)

        self.content_layout.addStretch()

        # Update next button to create snippet
        self.next_btn.setText("Create & Continue")

    def show_test_step(self):
        """Step 3: Test the snippet"""
        title = QLabel("Try It Out!")
        title.setObjectName("titleLabel")
        self.content_layout.addWidget(title)

        trigger = self.tutorial_snippet_trigger
        desc = QLabel(
            f"Your snippet is ready! Now let's test it:\n\n"
            f"1. Open any text editor or text field\n"
            f"2. Type '{trigger}' followed by Space or Enter\n"
            f"3. Watch it expand to '{self.tutorial_snippet_content}'"
        )
        desc.setObjectName("descLabel")
        desc.setWordWrap(True)
        self.content_layout.addWidget(desc)

        # Visual feedback area
        feedback_widget = QWidget()
        feedback_layout = QVBoxLayout(feedback_widget)
        feedback_layout.setContentsMargins(0, 24, 0, 24)
        feedback_layout.setAlignment(Qt.AlignCenter)

        self.waiting_label = QLabel(f"Waiting for you to type '{trigger}'...")
        self.waiting_label.setObjectName("waitingLabel")
        self.waiting_label.setAlignment(Qt.AlignCenter)
        feedback_layout.addWidget(self.waiting_label)

        self.success_label = QLabel("It worked!")
        self.success_label.setObjectName("successLabel")
        self.success_label.setAlignment(Qt.AlignCenter)
        self.success_label.setVisible(False)
        feedback_layout.addWidget(self.success_label)

        self.content_layout.addWidget(feedback_widget)

        # Add a skip option for those who can't test right now
        skip_test_label = QLabel("Can't test right now? Click 'Next' to continue anyway.")
        skip_test_label.setObjectName("descLabel")
        skip_test_label.setStyleSheet("color: #888888; font-size: 12px;")
        skip_test_label.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(skip_test_label)

        self.content_layout.addStretch()

        # Connect to trigger detection signal
        if self.parent_window and hasattr(self.parent_window, 'listener_thread'):
            self.parent_window.listener_thread.trigger_detected.connect(self.on_trigger_detected)

        # Reset detection counter
        self.trigger_detected_count = 0

    def show_complete_step(self):
        """Step 4: Completion and tips"""
        title = QLabel("You're All Set!")
        title.setObjectName("titleLabel")
        self.content_layout.addWidget(title)

        # Checkmark
        check_label = QLabel("✓")
        check_label.setStyleSheet("font-size: 48px; color: #4CAF50;")
        check_label.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(check_label)

        trigger = self.tutorial_snippet_trigger
        desc = QLabel(
            f"Your snippet '{trigger}' is working!\n\n"
            "Here are some ideas for useful snippets:\n"
            "  • ':email' → your email address\n"
            "  • ':addr' → your home/work address\n"
            "  • ':sig' → your email signature\n"
            "  • ':date' → today's date (use {{date}} for dynamic)\n\n"
            "Click the tray icon anytime to create more snippets."
        )
        desc.setObjectName("descLabel")
        desc.setWordWrap(True)
        self.content_layout.addWidget(desc)

        self.content_layout.addStretch()

        # Update finish button
        self.next_btn.setText("Open SnipForge")

    def on_trigger_detected(self, snippet):
        """Handle when any trigger is detected during step 3"""
        if self.current_step != 2:
            return

        # Check if it's our tutorial snippet
        if snippet.get('trigger', '') == self.tutorial_snippet_trigger:
            self.trigger_detected_count += 1

            # Show success
            self.waiting_label.setVisible(False)
            self.success_label.setVisible(True)

            # Auto-advance after a short delay
            QTimer.singleShot(1500, self.auto_advance_from_test)

    def auto_advance_from_test(self):
        """Auto-advance from test step after success"""
        if self.current_step == 2:
            self.show_step(3)

    def on_dont_show_changed(self, state):
        """Handle checkbox state change"""
        self.dont_show_again = (state == Qt.Checked)

    def on_skip(self):
        """Handle skip button click"""
        self.dont_show_again = True
        self.accept()

    def on_back(self):
        """Handle back button click"""
        if self.current_step > 0:
            self.show_step(self.current_step - 1)

    def on_next(self):
        """Handle next/finish button click"""
        if self.current_step == 1:
            # Create the snippet before advancing
            self.create_tutorial_snippet()

        if self.current_step == 3:
            # Finish - accept the dialog
            self.accept()
        else:
            self.show_step(self.current_step + 1)

    def create_tutorial_snippet(self):
        """Create the tutorial snippet"""
        if self.snippet_created:
            return

        trigger = self.trigger_input.text().strip() if hasattr(self, 'trigger_input') else self.tutorial_snippet_trigger
        content = self.content_input.text().strip() if hasattr(self, 'content_input') else self.tutorial_snippet_content

        if not trigger:
            trigger = self.tutorial_snippet_trigger
        if not content:
            content = self.tutorial_snippet_content

        # Store for later reference
        self.tutorial_snippet_trigger = trigger
        self.tutorial_snippet_content = content

        # Check if snippet with this trigger already exists
        if self.parent_window:
            for existing in self.parent_window.snippets:
                if existing.get('trigger', '') == trigger:
                    # Snippet already exists, don't create duplicate
                    self.snippet_created = True
                    return

            # Create the snippet
            tutorial_snippet = {
                'folder': 'General',
                'trigger': trigger,
                'description': 'My first snippet (Tutorial)',
                'type': 'universal',
                'content': content
            }
            self.parent_window.snippets.append(tutorial_snippet)
            self.parent_window.save_snippets()
            self.parent_window.refresh_tree()
            self.snippet_created = True

    def closeEvent(self, event):
        """Handle dialog close"""
        # Disconnect signal if connected
        if self.parent_window and hasattr(self.parent_window, 'listener_thread'):
            try:
                self.parent_window.listener_thread.trigger_detected.disconnect(self.on_trigger_detected)
            except:
                pass
        super().closeEvent(event)


class FormattingSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter to show bold, italic, and underline formatting in the editor"""

    def __init__(self, document):
        super().__init__(document)

    def highlightBlock(self, text):
        """Apply formatting to the text block with support for nested formats"""
        # Track formatting for each character position
        # Each position maps to: {'bold': bool, 'italic': bool, 'underline': bool, 'marker': bool}
        char_formats = [{} for _ in range(len(text))]

        # Bold: **text**
        bold_pattern = re.compile(r'\*\*(.+?)\*\*')
        for match in bold_pattern.finditer(text):
            # Mark the ** markers
            for i in range(match.start(), match.start() + 2):
                char_formats[i]['marker'] = True
            for i in range(match.end() - 2, match.end()):
                char_formats[i]['marker'] = True
            # Mark content as bold
            for i in range(match.start() + 2, match.end() - 2):
                char_formats[i]['bold'] = True

        # Italic: *text* (but not **text**)
        italic_pattern = re.compile(r'(?<!\*)\*([^*]+?)\*(?!\*)')
        for match in italic_pattern.finditer(text):
            # Mark the * markers
            char_formats[match.start()]['marker'] = True
            char_formats[match.end() - 1]['marker'] = True
            # Mark content as italic
            for i in range(match.start() + 1, match.end() - 1):
                char_formats[i]['italic'] = True

        # Underline: <u>text</u>
        underline_pattern = re.compile(r'<u>(.+?)</u>', re.IGNORECASE)
        for match in underline_pattern.finditer(text):
            # Mark the <u> and </u> markers
            for i in range(match.start(), match.start() + 3):
                char_formats[i]['marker'] = True
            for i in range(match.end() - 4, match.end()):
                char_formats[i]['marker'] = True
            # Mark content as underlined
            for i in range(match.start() + 3, match.end() - 4):
                char_formats[i]['underline'] = True

        # Apply combined formats to each character
        i = 0
        while i < len(text):
            fmt = char_formats[i]
            if not fmt:
                i += 1
                continue

            # Find run of characters with same formatting
            j = i + 1
            while j < len(text) and char_formats[j] == fmt:
                j += 1

            # Build the QTextCharFormat for this run
            text_format = QTextCharFormat()
            if fmt.get('marker'):
                # Make markers nearly invisible (tiny font, dim color)
                text_format.setFontPointSize(1)
                text_format.setForeground(QColor(30, 30, 30, 50))  # Nearly invisible
            if fmt.get('bold'):
                text_format.setFontWeight(QFont.Bold)
            if fmt.get('italic'):
                text_format.setFontItalic(True)
            if fmt.get('underline'):
                text_format.setFontUnderline(True)

            self.setFormat(i, j - i, text_format)
            i = j


class RichContentEdit(QTextEdit):
    """QTextEdit that captures HTML content when pasting from rich sources"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rich_html = None  # Stores HTML if pasted from rich source
        # Apply syntax highlighting for formatting
        self.highlighter = FormattingSyntaxHighlighter(self.document())

    def keyPressEvent(self, event):
        """Handle Enter key to auto-continue bullet/numbered/checkbox lists"""
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            cursor = self.textCursor()
            # Get the current line text
            cursor.movePosition(cursor.StartOfBlock, cursor.MoveAnchor)
            cursor.movePosition(cursor.EndOfBlock, cursor.KeepAnchor)
            current_line = cursor.selectedText()

            # Check for bullet point (•, -, *)
            bullet_match = re.match(r'^(\s*)(•|-|\*)\s', current_line)
            if bullet_match:
                indent = bullet_match.group(1)
                bullet = bullet_match.group(2)
                # If line is just the bullet (empty item), remove it and stop list
                if current_line.strip() == bullet:
                    cursor.removeSelectedText()
                    super().keyPressEvent(event)
                else:
                    # Continue the list
                    super().keyPressEvent(event)
                    self.insertPlainText(f'{indent}{bullet} ')
                return

            # Check for checkbox (☐ or ☑)
            checkbox_match = re.match(r'^(\s*)(☐|☑)\s', current_line)
            if checkbox_match:
                indent = checkbox_match.group(1)
                # If line is just the checkbox (empty item), remove it and stop list
                if current_line.strip() in ('☐', '☑'):
                    cursor.removeSelectedText()
                    super().keyPressEvent(event)
                else:
                    # Continue with unchecked checkbox
                    super().keyPressEvent(event)
                    self.insertPlainText(f'{indent}☐ ')
                return

            # Check for numbered list (1., 2., etc.)
            number_match = re.match(r'^(\s*)(\d+)\.\s', current_line)
            if number_match:
                indent = number_match.group(1)
                num = int(number_match.group(2))
                # If line is just the number (empty item), remove it and stop list
                if re.match(r'^\s*\d+\.\s*$', current_line):
                    cursor.removeSelectedText()
                    super().keyPressEvent(event)
                else:
                    # Continue with next number
                    super().keyPressEvent(event)
                    self.insertPlainText(f'{indent}{num + 1}. ')
                return

        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        """Override to capture HTML when pasting"""
        if source.hasHtml():
            html = source.html()
            # Check if this is actual rich content (not just plain text wrapped in HTML)
            if '<table' in html.lower() or '<img' in html.lower() or '<b>' in html.lower() or '<i>' in html.lower():
                self.rich_html = html
                print(f"Captured rich HTML content ({len(html)} chars)")
        # Always insert as plain text for editing
        if source.hasText():
            self.insertPlainText(source.text())
        else:
            super().insertFromMimeData(source)

    def setPlainText(self, text):
        """Override to clear rich_html when setting plain text"""
        self.rich_html = None
        super().setPlainText(text)

    def setRichHtml(self, html):
        """Set the stored rich HTML (for loading snippets)"""
        self.rich_html = html

    def getRichHtml(self):
        """Get the stored rich HTML"""
        return self.rich_html

    def hasRichContent(self):
        """Check if rich HTML content is stored"""
        return self.rich_html is not None


class SnippetEditorWidget(QWidget):
    """Widget for creating/editing snippets (embedded in main window)"""

    save_requested = pyqtSignal(dict)
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snippet = {}
        self.is_editing = False
        self.edit_index = -1
        self.snippets_list = []  # Reference to all snippets for Insert Snippet feature
        self.date_format_getter = lambda: '%m/%d/%Y'  # Default date format getter
        self.time_format_getter = lambda: '%I:%M %p'  # Default time format getter
        self.is_light_theme = False  # Track current theme for dialog styling

        # Emoji picker data (lazy-loaded)
        self.emoji_database = None      # Categorized emoji data
        self.emoji_favorites = []       # User's favorite emojis
        self.custom_emojis = []         # Custom emoji list
        self.emoji_search_index = {}    # Name -> emoji for search

        self.init_ui()

    def set_date_format_getter(self, getter):
        """Set the function to get the current date format"""
        self.date_format_getter = getter

    def set_time_format_getter(self, getter):
        """Set the function to get the current time format"""
        self.time_format_getter = getter

    def init_ui(self):
        # Make widget background transparent to show main window background
        self.setStyleSheet("background: transparent;")

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(24)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # Left column - Main content
        left_column = QVBoxLayout()
        left_column.setSpacing(12)

        # Header row with back button and title (back button on left like browser)
        header_layout = QHBoxLayout()

        # Back button (chevron style, on left - like Brave browser back button)
        self.back_btn = QPushButton("<")
        self.back_btn.setObjectName("backBtn")
        self.back_btn.setFixedSize(28, 28)
        self.back_btn.clicked.connect(self.cancel_requested.emit)
        # Styles defined in MainWindow themes - these are fallbacks
        self.back_btn_style_dark = ""
        self.back_btn_style_light = ""
        header_layout.addWidget(self.back_btn)

        # Title (after back button)
        self.title_label = QLabel("New Snippet")
        self.title_label.setStyleSheet("""
            QLabel {
                font-size: 20px;
                font-weight: 600;
                color: #FF6B00;
                padding-bottom: 8px;
                margin-left: 8px;
            }
        """)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        left_column.addLayout(header_layout)

        # Trigger
        trigger_layout = QHBoxLayout()
        trigger_layout.addWidget(QLabel("Shortcut:"))
        self.trigger_input = QLineEdit()
        self.trigger_input.setPlaceholderText("e.g., :email or /sig")
        trigger_layout.addWidget(self.trigger_input)
        left_column.addLayout(trigger_layout)

        # Description
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("Label:"))
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Optional description")
        desc_layout.addWidget(self.desc_input)
        left_column.addLayout(desc_layout)

        # Folder
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Folder:"))
        self.folder_combo = QComboBox()
        self.folder_combo.setEditable(True)
        self.folder_combo.setInsertPolicy(QComboBox.NoInsert)
        self.folder_combo.lineEdit().setPlaceholderText("Select or create folder")
        self.folder_combo.addItem("General")
        folder_layout.addWidget(self.folder_combo)
        left_column.addLayout(folder_layout)

        # Content
        left_column.addWidget(QLabel("Content:"))

        # Text formatting toolbar - Row 1
        format_toolbar = QHBoxLayout()
        format_toolbar.setSpacing(4)

        # Common style for format buttons (dark mode default)
        self.format_btn_style_dark = """
            QPushButton {
                background-color: rgba(60, 60, 60, 200);
                color: #E0E0E0;
                border: 1px solid #555555;
                border-radius: 4px;
                font-weight: bold;
                min-width: 32px;
                max-width: 32px;
                min-height: 28px;
                max-height: 28px;
            }
            QPushButton:hover {
                background-color: rgba(80, 80, 80, 220);
                border-color: #FF6B00;
            }
            QPushButton:pressed {
                background-color: rgba(100, 100, 100, 240);
            }
        """
        self.format_btn_style_light = """
            QPushButton {
                background-color: rgba(240, 240, 240, 230);
                color: #333333;
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                font-weight: bold;
                min-width: 32px;
                max-width: 32px;
                min-height: 28px;
                max-height: 28px;
            }
            QPushButton:hover {
                background-color: rgba(220, 220, 220, 240);
                border-color: #FF6B00;
            }
            QPushButton:pressed {
                background-color: rgba(200, 200, 200, 250);
            }
        """

        self.bold_btn = QPushButton("B")
        self.bold_btn.setToolTip("Bold (wrap selected text with **)")
        self.bold_btn.clicked.connect(lambda: self.insert_format_wrapper('**', '**'))
        self.bold_btn.setStyleSheet(self.format_btn_style_dark)
        format_toolbar.addWidget(self.bold_btn)

        self.italic_btn = QPushButton("I")
        self.italic_btn.setToolTip("Italic (wrap selected text with *)")
        self.italic_btn.clicked.connect(lambda: self.insert_format_wrapper('*', '*'))
        self.italic_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-style: italic; }")
        format_toolbar.addWidget(self.italic_btn)

        self.underline_btn = QPushButton("U")
        self.underline_btn.setToolTip("Underline (wrap selected text with <u></u>)")
        self.underline_btn.clicked.connect(lambda: self.insert_format_wrapper('<u>', '</u>'))
        self.underline_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { text-decoration: underline; }")
        format_toolbar.addWidget(self.underline_btn)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("QFrame { color: #555555; }")
        sep1.setFixedWidth(2)
        format_toolbar.addWidget(sep1)

        self.link_btn = QPushButton("🔗")
        self.link_btn.setToolTip("Hyperlink (insert link at cursor)")
        self.link_btn.clicked.connect(self.insert_hyperlink)
        self.link_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-weight: normal; }")
        format_toolbar.addWidget(self.link_btn)

        self.image_insert_btn = QPushButton("🖼")
        self.image_insert_btn.setToolTip("Insert image reference")
        self.image_insert_btn.clicked.connect(self.insert_image_reference)
        self.image_insert_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-weight: normal; }")
        format_toolbar.addWidget(self.image_insert_btn)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("QFrame { color: #555555; }")
        sep2.setFixedWidth(2)
        format_toolbar.addWidget(sep2)

        self.bullet_list_btn = QPushButton("•")
        self.bullet_list_btn.setToolTip("Bullet list")
        self.bullet_list_btn.clicked.connect(self.insert_bullet_list)
        self.bullet_list_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-weight: normal; font-size: 16px; }")
        format_toolbar.addWidget(self.bullet_list_btn)

        self.numbered_list_btn = QPushButton("1.")
        self.numbered_list_btn.setToolTip("Numbered list")
        self.numbered_list_btn.clicked.connect(self.insert_numbered_list)
        self.numbered_list_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-size: 11px; }")
        format_toolbar.addWidget(self.numbered_list_btn)

        self.checkbox_btn = QPushButton("☐")
        self.checkbox_btn.setToolTip("Checkbox list")
        self.checkbox_btn.clicked.connect(self.insert_checkbox_list)
        self.checkbox_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-weight: normal; font-size: 14px; }")
        format_toolbar.addWidget(self.checkbox_btn)

        format_toolbar.addStretch()

        left_column.addLayout(format_toolbar)

        # Text formatting toolbar - Row 2
        format_toolbar2 = QHBoxLayout()
        format_toolbar2.setSpacing(4)

        self.emoji_btn = QPushButton("Emoji")
        self.emoji_btn.setToolTip("Insert emoji")
        self.emoji_btn.clicked.connect(self.show_emoji_picker)
        self.emoji_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-weight: normal; min-width: 50px; max-width: 50px; }")
        format_toolbar2.addWidget(self.emoji_btn)

        # Separator
        sep4 = QFrame()
        sep4.setFrameShape(QFrame.VLine)
        sep4.setStyleSheet("QFrame { color: #555555; }")
        sep4.setFixedWidth(2)
        format_toolbar2.addWidget(sep4)

        self.find_btn = QPushButton("Find")
        self.find_btn.setToolTip("Find and replace")
        self.find_btn.clicked.connect(self.show_find_replace)
        self.find_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-weight: normal; min-width: 45px; max-width: 45px; }")
        format_toolbar2.addWidget(self.find_btn)

        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setToolTip("Undo (Ctrl+Z)")
        self.undo_btn.clicked.connect(lambda: self.content_input.undo())
        self.undo_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-weight: normal; min-width: 50px; max-width: 50px; }")
        format_toolbar2.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("Redo")
        self.redo_btn.setToolTip("Redo (Ctrl+Y)")
        self.redo_btn.clicked.connect(lambda: self.content_input.redo())
        self.redo_btn.setStyleSheet(self.format_btn_style_dark + "QPushButton { font-weight: normal; min-width: 50px; max-width: 50px; }")
        format_toolbar2.addWidget(self.redo_btn)

        format_toolbar2.addStretch()

        left_column.addLayout(format_toolbar2)

        # Store format buttons for theme updates
        self.format_buttons = [
            self.bold_btn, self.italic_btn, self.underline_btn,
            self.link_btn, self.image_insert_btn, self.bullet_list_btn, self.numbered_list_btn,
            self.checkbox_btn, self.emoji_btn, self.find_btn, self.undo_btn, self.redo_btn
        ]

        self.content_input = RichContentEdit()
        left_column.addWidget(self.content_input)

        # Buttons at bottom
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        back_btn = QPushButton("Back")
        back_btn.clicked.connect(self.on_cancel)
        back_btn.setMinimumWidth(100)
        back_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #B0B0B0;
                border: 2px solid #424242;
            }
            QPushButton:hover {
                background-color: #252525;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #1E1E1E;
            }
        """)
        button_layout.addWidget(back_btn)
        button_layout.addStretch()

        preview_btn = QPushButton("Preview")
        preview_btn.clicked.connect(self.show_preview)
        preview_btn.setMinimumWidth(100)
        preview_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #4A90D9;
                border: 2px solid #4A90D9;
            }
            QPushButton:hover {
                background-color: #1A2A3A;
            }
            QPushButton:pressed {
                background-color: #0A1A2A;
            }
        """)
        button_layout.addWidget(preview_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.on_save)
        self.save_btn.setMinimumWidth(100)
        # Dark mode style (default)
        self.save_btn_style_dark = """
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: 2px solid #FF8C00;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
                border-color: #FFA500;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
        """
        self.save_btn_style_light = """
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: 2px solid #E65100;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
                border-color: #FF6B00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
        """
        self.save_btn.setStyleSheet(self.save_btn_style_dark)
        button_layout.addWidget(self.save_btn)
        left_column.addLayout(button_layout)

        # Right column - Insert commands
        right_column = QVBoxLayout()
        right_column.setSpacing(8)

        commands_header = QLabel("Dynamic Commands")
        commands_header.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: 600;
                color: #FF6B00;
                padding-bottom: 8px;
            }
        """)
        right_column.addWidget(commands_header)

        # Basic Commands section
        basic_label = QLabel("BASIC")
        basic_label.setStyleSheet("""
            QLabel {
                color: #757575;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 1px;
                margin-top: 8px;
            }
        """)
        right_column.addWidget(basic_label)

        # Command button styles for dark and light modes
        self.cmd_btn_style_dark = """
            QPushButton {
                background-color: rgba(60, 40, 30, 180);
                color: #4A90D9;
                border: 1px solid rgba(255, 107, 0, 0.4);
                border-radius: 4px;
                text-align: left;
                padding-left: 12px;
            }
            QPushButton:hover {
                background-color: rgba(80, 50, 35, 200);
                border-color: #FF6B00;
                color: #5BA3E0;
            }
            QPushButton:pressed {
                background-color: rgba(100, 60, 40, 220);
            }
        """
        self.cmd_btn_style_light = """
            QPushButton {
                background-color: rgba(230, 230, 230, 220);
                color: #2563EB;
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                text-align: left;
                padding-left: 12px;
            }
            QPushButton:hover {
                background-color: rgba(220, 220, 220, 240);
                border-color: #FF6B00;
                color: #1D4ED8;
            }
            QPushButton:pressed {
                background-color: rgba(200, 200, 200, 250);
            }
        """

        # Store command buttons for theme updates
        self.cmd_buttons = []

        today_btn = QPushButton("  Today's Date")
        today_btn.setToolTip("Insert today's date")
        today_btn.clicked.connect(self.insert_today_date)
        today_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(today_btn)
        self.cmd_buttons.append(today_btn)

        select_date_btn = QPushButton("  Select Date")
        select_date_btn.setToolTip("Pick a date from calendar")
        select_date_btn.clicked.connect(self.show_calendar_dialog)
        select_date_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(select_date_btn)
        self.cmd_buttons.append(select_date_btn)

        time_btn = QPushButton("  Time")
        time_btn.setToolTip("Insert current time")
        time_btn.clicked.connect(self.insert_current_time)
        time_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(time_btn)
        self.cmd_buttons.append(time_btn)

        clipboard_btn = QPushButton("  Clipboard")
        clipboard_btn.setToolTip("Insert clipboard content")
        clipboard_btn.clicked.connect(lambda: self.insert_variable('{{clipboard}}'))
        clipboard_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(clipboard_btn)
        self.cmd_buttons.append(clipboard_btn)

        cursor_btn = QPushButton("  Cursor Position")
        cursor_btn.setToolTip("Place cursor here after expansion")
        cursor_btn.clicked.connect(lambda: self.insert_variable('{{cursor}}'))
        cursor_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(cursor_btn)
        self.cmd_buttons.append(cursor_btn)

        snippet_btn = QPushButton("  Insert Snippet")
        snippet_btn.setToolTip("Embed another snippet")
        snippet_btn.clicked.connect(self.insert_snippet_dialog)
        snippet_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(snippet_btn)
        self.cmd_buttons.append(snippet_btn)

        # Forms section
        self.forms_label = QLabel("FORMS")
        self.forms_label.setStyleSheet("""
            QLabel {
                color: #757575;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 1px;
                margin-top: 16px;
            }
        """)
        right_column.addWidget(self.forms_label)

        text_field_btn = QPushButton("  Text Field")
        text_field_btn.setToolTip("Single line text input")
        text_field_btn.clicked.connect(self.insert_text_field_dialog)
        text_field_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(text_field_btn)
        self.cmd_buttons.append(text_field_btn)

        dropdown_btn = QPushButton("  Dropdown Menu")
        dropdown_btn.setToolTip("Multiple choice dropdown")
        dropdown_btn.clicked.connect(self.insert_dropdown_dialog)
        dropdown_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(dropdown_btn)
        self.cmd_buttons.append(dropdown_btn)

        toggle_btn = QPushButton("  Toggle Section")
        toggle_btn.setToolTip("Conditional section - include/exclude content")
        toggle_btn.clicked.connect(self.insert_toggle_dialog)
        toggle_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(toggle_btn)
        self.cmd_buttons.append(toggle_btn)

        multi_btn = QPushButton("  Multiple Selection")
        multi_btn.setToolTip("Select multiple options")
        multi_btn.clicked.connect(self.insert_multi_select_dialog)
        multi_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(multi_btn)
        self.cmd_buttons.append(multi_btn)

        date_picker_btn = QPushButton("  Date Picker")
        date_picker_btn.setToolTip("Calendar date selector")
        date_picker_btn.clicked.connect(self.insert_date_picker_dialog)
        date_picker_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(date_picker_btn)
        self.cmd_buttons.append(date_picker_btn)

        calc_btn = QPushButton("  Calculation")
        calc_btn.setToolTip("Dynamic calculation with math operations")
        calc_btn.clicked.connect(self.insert_calculation_dialog)
        calc_btn.setStyleSheet(self.cmd_btn_style_dark)
        right_column.addWidget(calc_btn)
        self.cmd_buttons.append(calc_btn)

        right_column.addStretch()

        # Help text at bottom
        self.help_text = QLabel("""<b>Syntax Reference:</b><br>
<b>Text:</b> {{name}}<br>
<b>Dropdown:</b> {{name=a|b}}<br>
<b>Toggle:</b> {{name:toggle}}...{{/name:toggle}}<br>
<b>Multi:</b> {{name:multi=a|b}}<br>
<b>Date Picker:</b> {{name:date}}<br>
<b>Date Math:</b> {{date+1}} {{date-1}}<br>
<b>Calc:</b> {{calc:expression}}<br>
<b>Snippet:</b> {{snippet:trigger}}""")
        self.help_text.setWordWrap(True)
        self.help_text_style_dark = """
            QLabel {
                padding: 16px;
                background-color: rgba(50, 35, 25, 200);
                color: #C0C0C0;
                border-radius: 4px;
                border-left: 4px solid #FF6B00;
                font-size: 12px;
            }
        """
        self.help_text_style_light = """
            QLabel {
                padding: 16px;
                background-color: rgba(240, 240, 240, 230);
                color: #424242;
                border-radius: 4px;
                border-left: 4px solid #FF6B00;
                font-size: 12px;
            }
        """
        self.help_text.setStyleSheet(self.help_text_style_dark)
        right_column.addWidget(self.help_text)

        # Wrap right column in a scroll area to handle small window sizes
        right_widget = QWidget()
        right_widget.setLayout(right_column)
        right_widget.setStyleSheet("background: transparent;")

        right_scroll = QScrollArea()
        right_scroll.setWidget(right_widget)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 107, 0, 0.5);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        # Add columns to main layout
        main_layout.addLayout(left_column, 3)
        main_layout.addWidget(right_scroll, 1)

    def update_theme(self, is_light_theme):
        """Update editor widget styling based on current theme"""
        self.is_light_theme = is_light_theme
        # Define button-specific style modifiers
        btn_style_modifiers = {
            'italic_btn': "QPushButton { font-style: italic; }",
            'underline_btn': "QPushButton { text-decoration: underline; }",
            'link_btn': "QPushButton { font-weight: normal; }",
            'image_insert_btn': "QPushButton { font-weight: normal; }",
            'bullet_list_btn': "QPushButton { font-weight: normal; font-size: 16px; }",
            'numbered_list_btn': "QPushButton { font-size: 11px; }",
            'emoji_btn': "QPushButton { font-weight: normal; min-width: 50px; max-width: 50px; }",
            'find_btn': "QPushButton { font-weight: normal; min-width: 45px; max-width: 45px; }",
            'undo_btn': "QPushButton { font-weight: normal; min-width: 50px; max-width: 50px; }",
            'redo_btn': "QPushButton { font-weight: normal; min-width: 50px; max-width: 50px; }",
        }

        if is_light_theme:
            # Light mode styles
            self.back_btn.setStyleSheet(self.back_btn_style_light)
            self.save_btn.setStyleSheet(self.save_btn_style_light)
            for btn in self.cmd_buttons:
                btn.setStyleSheet(self.cmd_btn_style_light)
            for btn in self.format_buttons:
                btn_name = None
                for name, widget in [('italic_btn', self.italic_btn), ('underline_btn', self.underline_btn),
                                     ('link_btn', self.link_btn),
                                     ('image_insert_btn', self.image_insert_btn), ('bullet_list_btn', self.bullet_list_btn),
                                     ('numbered_list_btn', self.numbered_list_btn), ('emoji_btn', self.emoji_btn),
                                     ('find_btn', self.find_btn), ('undo_btn', self.undo_btn), ('redo_btn', self.redo_btn)]:
                    if btn == widget:
                        btn_name = name
                        break
                if btn_name and btn_name in btn_style_modifiers:
                    btn.setStyleSheet(self.format_btn_style_light + btn_style_modifiers[btn_name])
                else:
                    btn.setStyleSheet(self.format_btn_style_light)
            self.help_text.setStyleSheet(self.help_text_style_light)
        else:
            # Dark mode styles
            self.back_btn.setStyleSheet(self.back_btn_style_dark)
            self.save_btn.setStyleSheet(self.save_btn_style_dark)
            for btn in self.cmd_buttons:
                btn.setStyleSheet(self.cmd_btn_style_dark)
            for btn in self.format_buttons:
                btn_name = None
                for name, widget in [('italic_btn', self.italic_btn), ('underline_btn', self.underline_btn),
                                     ('link_btn', self.link_btn),
                                     ('image_insert_btn', self.image_insert_btn), ('bullet_list_btn', self.bullet_list_btn),
                                     ('numbered_list_btn', self.numbered_list_btn), ('emoji_btn', self.emoji_btn),
                                     ('find_btn', self.find_btn), ('undo_btn', self.undo_btn), ('redo_btn', self.redo_btn)]:
                    if btn == widget:
                        btn_name = name
                        break
                if btn_name and btn_name in btn_style_modifiers:
                    btn.setStyleSheet(self.format_btn_style_dark + btn_style_modifiers[btn_name])
                else:
                    btn.setStyleSheet(self.format_btn_style_dark)
            self.help_text.setStyleSheet(self.help_text_style_dark)

    def set_folders(self, folders):
        """Set the available folders in the combo box"""
        current_text = self.folder_combo.currentText()
        self.folder_combo.clear()
        for folder in folders:
            self.folder_combo.addItem(folder)
        # Restore selection if it exists
        index = self.folder_combo.findText(current_text)
        if index >= 0:
            self.folder_combo.setCurrentIndex(index)

    def load_snippet(self, snippet=None, index=-1, pre_selected_folder=None):
        """Load a snippet for editing or clear for new"""
        self.snippet = snippet or {}
        self.edit_index = index
        self.is_editing = index >= 0

        self.title_label.setText("Edit Snippet" if self.is_editing else "New Snippet")
        self.trigger_input.setText(self.snippet.get('trigger', ''))
        self.desc_input.setText(self.snippet.get('description', ''))
        self.content_input.setPlainText(self.snippet.get('content', ''))
        # Load rich HTML if available
        if self.snippet.get('rich_html'):
            self.content_input.setRichHtml(self.snippet.get('rich_html'))

        # Set folder selection (use pre_selected_folder for new snippets)
        if pre_selected_folder and not self.is_editing:
            folder = pre_selected_folder
        else:
            folder = self.snippet.get('folder', 'General')
        if not folder:
            folder = 'General'
        index_in_combo = self.folder_combo.findText(folder)
        if index_in_combo >= 0:
            self.folder_combo.setCurrentIndex(index_in_combo)
        else:
            # Folder not in list, add it
            self.folder_combo.addItem(folder)
            self.folder_combo.setCurrentText(folder)

    def insert_variable(self, variable):
        """Insert a variable at cursor position in content"""
        cursor = self.content_input.textCursor()
        cursor.insertText(variable)
        self.content_input.setFocus()

    def insert_format_wrapper(self, prefix, suffix):
        """Wrap selected text with format markers, or insert at cursor if no selection"""
        cursor = self.content_input.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            cursor.insertText(prefix + selected_text + suffix)
        else:
            cursor.insertText(prefix + suffix)
            # Move cursor between the markers
            cursor.movePosition(cursor.Left, cursor.MoveAnchor, len(suffix))
            self.content_input.setTextCursor(cursor)
        self.content_input.setFocus()

    def insert_hyperlink(self):
        """Insert a hyperlink at cursor position"""
        cursor = self.content_input.textCursor()
        selected_text = cursor.selectedText() if cursor.hasSelection() else ""

        url, ok = self.get_text_input('Insert Hyperlink', 'Enter URL:', 'https://')
        if ok and url:
            if selected_text:
                # Use selected text as link text
                link_text = f'<a href="{url}">{selected_text}</a>'
            else:
                # Prompt for link text
                text, ok2 = self.get_text_input('Link Text', 'Enter link text:', url)
                if ok2:
                    link_text = f'<a href="{url}">{text}</a>'
                else:
                    return
            cursor.insertText(link_text)
        self.content_input.setFocus()

    def insert_image_reference(self):
        """Insert an image reference at cursor position"""
        # Save cursor position before dialog opens
        cursor = self.content_input.textCursor()
        cursor_pos = cursor.position()

        # Use same pattern as working dialogs - main window as parent
        main_window = self.window()
        dialog = QFileDialog(main_window)
        dialog.setWindowTitle("Select Image")
        dialog.setDirectory(str(Path.home()))
        dialog.setNameFilter("Image Files (*.png *.jpg *.jpeg *.gif *.bmp);;All Files (*)")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setStyleSheet(self.get_file_dialog_stylesheet())

        if dialog.exec_() == QDialog.Accepted:
            files = dialog.selectedFiles()
            if files:
                file_path = files[0]
                # Restore cursor position after dialog closes
                cursor = self.content_input.textCursor()
                cursor.setPosition(cursor_pos)
                self.content_input.setTextCursor(cursor)
                # Insert image variable that will be processed during expansion
                self.insert_variable(f'{{{{image:{file_path}}}}}')

    def insert_bullet_list(self):
        """Insert bullet list items"""
        cursor = self.content_input.textCursor()
        if cursor.hasSelection():
            # Convert selected lines to bullet list
            selected_text = cursor.selectedText()
            lines = selected_text.split('\u2029')  # QTextEdit uses paragraph separator
            bulleted = '\n'.join(f'• {line}' for line in lines if line.strip())
            cursor.insertText(bulleted)
        else:
            # Insert single bullet point
            cursor.insertText('• ')
        self.content_input.setTextCursor(cursor)
        self.content_input.setFocus()

    def insert_numbered_list(self):
        """Insert numbered list items"""
        cursor = self.content_input.textCursor()
        if cursor.hasSelection():
            # Convert selected lines to numbered list
            selected_text = cursor.selectedText()
            lines = selected_text.split('\u2029')  # QTextEdit uses paragraph separator
            numbered = '\n'.join(f'{i+1}. {line}' for i, line in enumerate(lines) if line.strip())
            cursor.insertText(numbered)
        else:
            # Insert "1. " at cursor
            cursor.insertText('1. ')
        self.content_input.setTextCursor(cursor)
        self.content_input.setFocus()

    def insert_checkbox_list(self):
        """Insert checkbox list items"""
        cursor = self.content_input.textCursor()
        if cursor.hasSelection():
            # Convert selected lines to checkbox list
            selected_text = cursor.selectedText()
            lines = selected_text.split('\u2029')  # QTextEdit uses paragraph separator
            checkboxed = '\n'.join(f'☐ {line}' for line in lines if line.strip())
            cursor.insertText(checkboxed)
        else:
            # Insert checkbox at cursor
            cursor.insertText('☐ ')
        self.content_input.setTextCursor(cursor)
        self.content_input.setFocus()

    def get_dialog_stylesheet(self):
        """Get stylesheet for dialogs based on current theme"""
        if self.is_light_theme:
            return """
                QDialog { background-color: #F5F5F5; }
                QLabel { color: #212121; }
                QSpinBox { background-color: #FFFFFF; color: #212121; border: 1px solid #BDBDBD; padding: 4px; border-radius: 4px; }
                QLineEdit { background-color: #FFFFFF; color: #212121; border: 1px solid #BDBDBD; padding: 6px; border-radius: 4px; }
                QLineEdit:focus { border-color: #FF6B00; }
                QPushButton { background-color: #FF6B00; color: white; border: none; border-radius: 4px; padding: 8px 16px; }
                QPushButton:hover { background-color: #FF8C00; }
                QCheckBox { color: #212121; }
                QScrollArea { border: none; background-color: #F5F5F5; }
            """
        else:
            return """
                QDialog { background-color: #1E1E1E; }
                QLabel { color: #E0E0E0; }
                QSpinBox { background-color: #2A2A2A; color: #E0E0E0; border: 1px solid #424242; padding: 4px; border-radius: 4px; }
                QLineEdit { background-color: #2A2A2A; color: #E0E0E0; border: 1px solid #424242; padding: 6px; border-radius: 4px; }
                QLineEdit:focus { border-color: #FF6B00; }
                QPushButton { background-color: #FF6B00; color: white; border: none; border-radius: 4px; padding: 8px 16px; }
                QPushButton:hover { background-color: #FF8C00; }
                QCheckBox { color: #E0E0E0; }
                QScrollArea { border: none; background-color: #1E1E1E; }
            """

    def get_cancel_btn_stylesheet(self):
        """Get cancel button stylesheet based on current theme"""
        if self.is_light_theme:
            return "QPushButton { background-color: #9E9E9E; } QPushButton:hover { background-color: #BDBDBD; }"
        else:
            return "QPushButton { background-color: #424242; } QPushButton:hover { background-color: #555555; }"

    def get_file_dialog_stylesheet(self):
        """Get stylesheet for QFileDialog based on current theme"""
        if self.is_light_theme:
            return """
                QFileDialog, QDialog { background-color: #F5F5F5; }
                QWidget { background-color: #F5F5F5; color: #212121; }
                QFrame { background-color: #F5F5F5; }
                QTreeView, QListView, QTableView {
                    background-color: #FFFFFF; color: #212121;
                    border: 1px solid #BDBDBD;
                }
                QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {
                    background-color: #FFE0B2; color: #212121;
                }
                QLineEdit {
                    background-color: #FFFFFF; color: #212121;
                    border: 1px solid #BDBDBD; border-radius: 4px; padding: 4px;
                }
                QPushButton {
                    background-color: #FF6B00; color: white;
                    border: none; border-radius: 4px; padding: 6px 12px;
                }
                QPushButton:hover { background-color: #FF8C00; }
                QComboBox {
                    background-color: #FFFFFF; color: #212121;
                    border: 1px solid #BDBDBD; border-radius: 4px; padding: 4px;
                }
                QHeaderView::section {
                    background-color: #E0E0E0; color: #212121;
                    border: none; padding: 4px;
                }
                QToolButton {
                    background-color: #E0E0E0;
                    border: 1px solid #BDBDBD; border-radius: 4px; padding: 4px;
                }
                QToolButton:hover { background-color: #D0D0D0; }
            """
        else:
            return """
                QFileDialog, QDialog { background-color: #1E1E1E; }
                QWidget { background-color: #1E1E1E; color: #E0E0E0; }
                QFrame { background-color: #1E1E1E; }
                QTreeView, QListView, QTableView {
                    background-color: #2A2A2A; color: #E0E0E0;
                    border: 1px solid #424242;
                }
                QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {
                    background-color: #3D2814; color: #FFFFFF;
                }
                QLineEdit {
                    background-color: #2A2A2A; color: #E0E0E0;
                    border: 1px solid #424242; border-radius: 4px; padding: 4px;
                }
                QPushButton {
                    background-color: #FF6B00; color: white;
                    border: none; border-radius: 4px; padding: 6px 12px;
                }
                QPushButton:hover { background-color: #FF8C00; }
                QComboBox {
                    background-color: #2A2A2A; color: #E0E0E0;
                    border: 1px solid #424242; border-radius: 4px; padding: 4px;
                }
                QHeaderView::section {
                    background-color: #2A2A2A; color: #E0E0E0;
                    border: none; padding: 4px;
                }
                QToolButton {
                    background-color: #3D3D3D;
                    border: 1px solid #424242; border-radius: 4px; padding: 4px;
                }
                QToolButton:hover { background-color: #4A4A4A; }
            """

    def create_dialog(self, title, min_width=300, min_height=150):
        """Create a dialog with proper non-transparent background"""
        # Get the main window as parent to avoid inheriting transparent background
        main_window = self.window()
        dialog = QDialog(main_window)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(min_width, min_height)
        # Ensure dialog has solid background (not transparent)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setStyleSheet(self.get_dialog_stylesheet())
        return dialog

    def create_custom_spinbox(self, min_val=1, max_val=20, initial_val=3):
        """Create a custom spinbox widget with +/- buttons"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Value stored in a QLineEdit for direct editing
        container.value_edit = QLineEdit(str(initial_val))
        container.value_edit.setAlignment(Qt.AlignCenter)
        container.value_edit.setFixedWidth(36)
        container.value_edit.setFixedHeight(28)
        container.min_val = min_val
        container.max_val = max_val

        # Circular button style with orange accent
        if self.is_light_theme:
            btn_style = """
                QPushButton {
                    background-color: transparent;
                    border: 2px solid #FF6B00;
                    border-radius: 14px;
                    font-size: 18px;
                    font-weight: bold;
                    color: #FF6B00;
                    min-width: 28px;
                    max-width: 28px;
                    min-height: 28px;
                    max-height: 28px;
                }
                QPushButton:hover {
                    background-color: #FF6B00;
                    color: #FFFFFF;
                }
                QPushButton:pressed {
                    background-color: #E65C00;
                    border-color: #E65C00;
                    color: #FFFFFF;
                }
            """
            edit_style = """
                QLineEdit {
                    background-color: #FFFFFF;
                    border: 1px solid #BDBDBD;
                    border-radius: 4px;
                    color: #212121;
                    font-size: 14px;
                    font-weight: bold;
                }
            """
        else:
            btn_style = """
                QPushButton {
                    background-color: transparent;
                    border: 2px solid #FF6B00;
                    border-radius: 14px;
                    font-size: 18px;
                    font-weight: bold;
                    color: #FF6B00;
                    min-width: 28px;
                    max-width: 28px;
                    min-height: 28px;
                    max-height: 28px;
                }
                QPushButton:hover {
                    background-color: #FF6B00;
                    color: #FFFFFF;
                }
                QPushButton:pressed {
                    background-color: #E65C00;
                    border-color: #E65C00;
                    color: #FFFFFF;
                }
            """
            edit_style = """
                QLineEdit {
                    background-color: #2A2A2A;
                    border: 1px solid #555555;
                    border-radius: 4px;
                    color: #E0E0E0;
                    font-size: 14px;
                    font-weight: bold;
                }
            """

        # Minus button
        minus_btn = QPushButton("-")
        minus_btn.setStyleSheet(btn_style)
        minus_btn.setCursor(Qt.PointingHandCursor)

        # Plus button
        plus_btn = QPushButton("+")
        plus_btn.setStyleSheet(btn_style)
        plus_btn.setCursor(Qt.PointingHandCursor)

        # Value edit styling
        container.value_edit.setStyleSheet(edit_style)

        def clamp_value():
            try:
                val = int(container.value_edit.text())
                val = max(container.min_val, min(container.max_val, val))
                container.value_edit.setText(str(val))
            except ValueError:
                container.value_edit.setText(str(container.min_val))

        def decrease():
            try:
                current = int(container.value_edit.text())
                if current > container.min_val:
                    container.value_edit.setText(str(current - 1))
            except ValueError:
                container.value_edit.setText(str(container.min_val))

        def increase():
            try:
                current = int(container.value_edit.text())
                if current < container.max_val:
                    container.value_edit.setText(str(current + 1))
            except ValueError:
                container.value_edit.setText(str(container.min_val))

        minus_btn.clicked.connect(decrease)
        plus_btn.clicked.connect(increase)
        container.value_edit.editingFinished.connect(clamp_value)

        layout.addWidget(minus_btn)
        layout.addWidget(container.value_edit)
        layout.addWidget(plus_btn)

        # Add value() method to container
        def get_value():
            try:
                return int(container.value_edit.text())
            except ValueError:
                return container.min_val
        container.value = get_value

        return container

    def get_input_dialog_stylesheet(self):
        """Get stylesheet for QInputDialog based on current theme"""
        if self.is_light_theme:
            return """
                QInputDialog {
                    background-color: #F5F5F5;
                }
                QInputDialog QLabel {
                    color: #212121;
                }
                QInputDialog QLineEdit {
                    background-color: #FFFFFF;
                    color: #212121;
                    border: 1px solid #BDBDBD;
                    padding: 6px;
                    border-radius: 4px;
                }
                QInputDialog QLineEdit:focus {
                    border-color: #FF6B00;
                }
                QInputDialog QPushButton {
                    background-color: #FF6B00;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    min-width: 70px;
                }
                QInputDialog QPushButton:hover {
                    background-color: #FF8C00;
                }
                QInputDialog QComboBox {
                    background-color: #FFFFFF;
                    color: #212121;
                    border: 1px solid #BDBDBD;
                    padding: 6px;
                    border-radius: 4px;
                }
                QInputDialog QComboBox QAbstractItemView {
                    background-color: #FFFFFF;
                    color: #212121;
                    selection-background-color: #FFE0CC;
                }
            """
        else:
            return """
                QInputDialog {
                    background-color: #1E1E1E;
                }
                QInputDialog QLabel {
                    color: #E0E0E0;
                }
                QInputDialog QLineEdit {
                    background-color: #2A2A2A;
                    color: #E0E0E0;
                    border: 1px solid #424242;
                    padding: 6px;
                    border-radius: 4px;
                }
                QInputDialog QLineEdit:focus {
                    border-color: #FF6B00;
                }
                QInputDialog QPushButton {
                    background-color: #FF6B00;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    min-width: 70px;
                }
                QInputDialog QPushButton:hover {
                    background-color: #FF8C00;
                }
                QInputDialog QComboBox {
                    background-color: #2A2A2A;
                    color: #E0E0E0;
                    border: 1px solid #424242;
                    padding: 6px;
                    border-radius: 4px;
                }
                QInputDialog QComboBox QAbstractItemView {
                    background-color: #1E1E1E;
                    color: #E0E0E0;
                    selection-background-color: #3D2814;
                }
            """

    def get_text_input(self, title, label, default_text=''):
        """Show a styled text input dialog"""
        main_window = self.window()
        dialog = QInputDialog(main_window)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextValue(default_text)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setStyleSheet(self.get_input_dialog_stylesheet())

        if dialog.exec_() == QDialog.Accepted:
            return dialog.textValue(), True
        return '', False

    def get_item_input(self, title, label, items, current=0, editable=False):
        """Show a styled item selection dialog"""
        main_window = self.window()
        dialog = QInputDialog(main_window)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setComboBoxItems(items)
        dialog.setComboBoxEditable(editable)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setStyleSheet(self.get_input_dialog_stylesheet())

        if dialog.exec_() == QDialog.Accepted:
            return dialog.textValue(), True
        return '', False

    def insert_table(self):
        """Insert a markdown-style table using visual grid selector"""
        main_window = self.window()
        dialog = QDialog(main_window)
        dialog.setWindowTitle("Insert Table")
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setStyleSheet(self.get_dialog_stylesheet())

        # Grid dimensions
        max_cols = 10
        max_rows = 8
        cell_size = 24
        cell_gap = 3

        # Track selection
        dialog.selected_cols = 0
        dialog.selected_rows = 0

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        # Size label at top
        size_label = QLabel("Select size")
        size_label.setAlignment(Qt.AlignCenter)
        if self.is_light_theme:
            size_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #FF6B00; padding: 4px;")
        else:
            size_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #FF6B00; padding: 4px;")
        layout.addWidget(size_label)

        # Create grid container widget
        grid_widget = QWidget()
        grid_widget.setFixedSize(
            max_cols * (cell_size + cell_gap) + cell_gap,
            max_rows * (cell_size + cell_gap) + cell_gap
        )
        grid_widget.setCursor(Qt.PointingHandCursor)

        # Store cell buttons
        cells = []

        # Styling
        if self.is_light_theme:
            cell_default = f"""
                background-color: #F0F0F0;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                min-width: {cell_size}px; max-width: {cell_size}px;
                min-height: {cell_size}px; max-height: {cell_size}px;
            """
            cell_hover = f"""
                background-color: #FF6B00;
                border: 1px solid #E65C00;
                border-radius: 3px;
                min-width: {cell_size}px; max-width: {cell_size}px;
                min-height: {cell_size}px; max-height: {cell_size}px;
            """
        else:
            cell_default = f"""
                background-color: #3A3A3A;
                border: 1px solid #555555;
                border-radius: 3px;
                min-width: {cell_size}px; max-width: {cell_size}px;
                min-height: {cell_size}px; max-height: {cell_size}px;
            """
            cell_hover = f"""
                background-color: #FF6B00;
                border: 1px solid #E65C00;
                border-radius: 3px;
                min-width: {cell_size}px; max-width: {cell_size}px;
                min-height: {cell_size}px; max-height: {cell_size}px;
            """

        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(cell_gap)
        grid_layout.setContentsMargins(cell_gap, cell_gap, cell_gap, cell_gap)

        def update_grid(hover_col, hover_row):
            dialog.selected_cols = hover_col
            dialog.selected_rows = hover_row
            if hover_col > 0 and hover_row > 0:
                # Display as "rows × columns" (common convention)
                size_label.setText(f"{hover_row} rows × {hover_col} columns")
            else:
                size_label.setText("Select size")

            for row in range(max_rows):
                for col in range(max_cols):
                    cell = cells[row][col]
                    if col < hover_col and row < hover_row:
                        cell.setStyleSheet(cell_hover)
                    else:
                        cell.setStyleSheet(cell_default)

        def cell_clicked(col, row):
            dialog.selected_cols = col + 1
            dialog.selected_rows = row + 1
            dialog.accept()

        for row in range(max_rows):
            row_cells = []
            for col in range(max_cols):
                cell = QPushButton()
                cell.setStyleSheet(cell_default)
                cell.setFlat(True)
                cell.setCursor(Qt.PointingHandCursor)

                # Capture col/row in closure
                cell.enterEvent = lambda e, c=col, r=row: update_grid(c + 1, r + 1)
                cell.clicked.connect(lambda checked, c=col, r=row: cell_clicked(c, r))

                grid_layout.addWidget(cell, row, col)
                row_cells.append(cell)
            cells.append(row_cells)

        # Reset on mouse leave
        def grid_leave(event):
            update_grid(0, 0)
        grid_widget.leaveEvent = grid_leave

        layout.addWidget(grid_widget, alignment=Qt.AlignCenter)

        # Custom size link
        def show_custom_size():
            custom_dialog = QDialog(dialog)
            custom_dialog.setWindowTitle("Custom Table Size")
            custom_dialog.setAttribute(Qt.WA_TranslucentBackground, False)
            custom_dialog.setStyleSheet(self.get_dialog_stylesheet())

            custom_layout = QVBoxLayout(custom_dialog)
            custom_layout.setSpacing(16)

            # Row/column inputs
            inputs_layout = QHBoxLayout()
            inputs_layout.addWidget(QLabel("Columns:"))
            cols_spin = self.create_custom_spinbox(min_val=1, max_val=50, initial_val=10)
            inputs_layout.addWidget(cols_spin)
            inputs_layout.addSpacing(20)
            inputs_layout.addWidget(QLabel("Rows:"))
            rows_spin = self.create_custom_spinbox(min_val=1, max_val=100, initial_val=10)
            inputs_layout.addWidget(rows_spin)
            custom_layout.addLayout(inputs_layout)

            # Buttons
            custom_btn_layout = QHBoxLayout()
            custom_btn_layout.addStretch()
            custom_cancel = QPushButton("Cancel")
            custom_cancel.clicked.connect(custom_dialog.reject)
            custom_cancel.setStyleSheet(self.get_cancel_btn_stylesheet())
            custom_btn_layout.addWidget(custom_cancel)
            custom_insert = QPushButton("Insert")
            custom_insert.clicked.connect(custom_dialog.accept)
            custom_btn_layout.addWidget(custom_insert)
            custom_layout.addLayout(custom_btn_layout)

            if custom_dialog.exec_() == QDialog.Accepted:
                dialog.selected_cols = cols_spin.value()
                dialog.selected_rows = rows_spin.value()
                dialog.accept()

        custom_btn = QPushButton("Custom size...")
        custom_btn.setCursor(Qt.PointingHandCursor)
        if self.is_light_theme:
            custom_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    color: #FF6B00;
                    font-size: 13px;
                    text-decoration: underline;
                    padding: 4px;
                }
                QPushButton:hover {
                    color: #E65C00;
                }
            """)
        else:
            custom_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    color: #FF6B00;
                    font-size: 13px;
                    text-decoration: underline;
                    padding: 4px;
                }
                QPushButton:hover {
                    color: #FF8533;
                }
            """)
        custom_btn.clicked.connect(show_custom_size)
        layout.addWidget(custom_btn, alignment=Qt.AlignCenter)

        # Cancel button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        cancel_btn.setStyleSheet(self.get_cancel_btn_stylesheet())
        cancel_btn.setFixedWidth(80)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        if dialog.exec_() == QDialog.Accepted and dialog.selected_cols > 0 and dialog.selected_rows > 0:
            cols = dialog.selected_cols  # Columns (horizontal)
            rows = dialog.selected_rows  # Rows (vertical)

            # Build editable HTML table
            html_lines = ['<table border="1">']
            for r in range(rows):
                html_lines.append('  <tr>')
                for c in range(cols):
                    html_lines.append('    <td> </td>')
                html_lines.append('  </tr>')
            html_lines.append('</table>')

            self.insert_variable('\n' + '\n'.join(html_lines) + '\n')

    def show_emoji_picker(self):
        """Show Slack-like emoji picker dialog with full Unicode emoji set"""
        main_window = self.window()

        # Lazy-load emoji database from emoji library
        if self.emoji_database is None:
            self.emoji_database, self.emoji_search_index, self.emoji_categories = main_window.build_emoji_database()

        # Load favorites and custom emojis
        self.emoji_favorites = main_window.load_emoji_favorites()
        self.custom_emojis = main_window.load_custom_emojis()

        # Create dialog
        dialog = QDialog(main_window)
        dialog.setWindowTitle("Insert Emoji")
        dialog.setMinimumSize(520, 500)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)

        # Theme-aware styling
        if self.is_light_theme:
            bg_color = "#F5F5F5"
            text_color = "#212121"
            input_bg = "#FFFFFF"
            input_border = "#BDBDBD"
            scroll_bg = "#E8E8E8"
            tab_bg = "#E0E0E0"
            tab_selected_bg = "#FFFFFF"
            section_header_color = "#616161"
        else:
            bg_color = "#1E1E1E"
            text_color = "#E0E0E0"
            input_bg = "#2A2A2A"
            input_border = "#424242"
            scroll_bg = "#2A2A2A"
            tab_bg = "#333333"
            tab_selected_bg = "#424242"
            section_header_color = "#9E9E9E"

        dialog.setStyleSheet(f"""
            QDialog {{ background-color: {bg_color}; }}
            QLabel {{ color: {text_color}; }}
            QLineEdit {{
                background-color: {input_bg};
                color: {text_color};
                border: 1px solid {input_border};
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 14px;
            }}
            QLineEdit:focus {{ border-color: #FF6B00; }}
            QScrollArea {{
                border: none;
                background-color: {scroll_bg};
            }}
            QPushButton#closeBtn {{
                background-color: transparent;
                color: {text_color};
                border: none;
                font-size: 18px;
                font-weight: bold;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }}
            QPushButton#closeBtn:hover {{ color: #FF6B00; }}
            QPushButton#emojiBtn {{
                font-size: 24px;
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 0px;
                margin: 1px;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
            }}
            QPushButton#emojiBtn:hover {{
                background-color: rgba(255, 107, 0, 0.2);
                border-color: #FF6B00;
            }}
            QPushButton#categoryTab {{
                font-size: 20px;
                background-color: {tab_bg};
                border: none;
                border-bottom: 3px solid transparent;
                padding: 8px 6px;
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
            }}
            QPushButton#categoryTab:hover {{
                background-color: {tab_selected_bg};
            }}
            QPushButton#categoryTab:checked {{
                background-color: {tab_selected_bg};
                border-bottom: 3px solid #FF6B00;
            }}
            QPushButton#addEmojiBtn {{
                background-color: {tab_bg};
                color: #FF6B00;
                border: 1px dashed #FF6B00;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }}
            QPushButton#addEmojiBtn:hover {{
                background-color: rgba(255, 107, 0, 0.1);
            }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # Top row: Search + Close button
        top_row = QHBoxLayout()
        search_input = QLineEdit()
        search_input.setPlaceholderText("🔍 Search emojis...")
        top_row.addWidget(search_input, 1)

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeBtn")
        close_btn.clicked.connect(dialog.reject)
        top_row.addWidget(close_btn)
        layout.addLayout(top_row)

        # Category tab bar
        tab_bar = QHBoxLayout()
        tab_bar.setSpacing(0)
        category_buttons = []
        section_widgets = {}  # Map category_id -> (label_widget, grid_widget)

        for cat_id, cat_icon, cat_name in self.emoji_categories:
            tab_btn = QPushButton(cat_icon)
            tab_btn.setObjectName("categoryTab")
            tab_btn.setCheckable(True)
            tab_btn.setToolTip(cat_name)
            tab_btn.setCursor(Qt.PointingHandCursor)
            category_buttons.append((cat_id, tab_btn))
            tab_bar.addWidget(tab_btn)

        tab_bar.addStretch()
        layout.addLayout(tab_bar)

        # Scroll area for emoji grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"background-color: {scroll_bg};")

        emoji_container = QWidget()
        emoji_container.setStyleSheet(f"background-color: {scroll_bg};")
        emoji_main_layout = QVBoxLayout(emoji_container)
        emoji_main_layout.setSpacing(16)
        emoji_main_layout.setContentsMargins(8, 8, 8, 8)

        # Store all emoji buttons for filtering
        all_emoji_buttons = []
        EMOJIS_PER_ROW = 10

        # Emoji font
        emoji_font = QFont()
        emoji_font.setFamily("Noto Color Emoji")
        emoji_font.setPointSize(18)

        # Container for favorites section (will be rebuilt when favorites change)
        favorites_container = QWidget()
        favorites_container.setStyleSheet(f"background-color: {scroll_bg};")
        favorites_layout = QVBoxLayout(favorites_container)
        favorites_layout.setSpacing(4)
        favorites_layout.setContentsMargins(0, 0, 0, 0)

        def rebuild_favorites_section():
            """Rebuild the favorites section without closing the dialog"""
            # Clear existing widgets
            while favorites_layout.count():
                item = favorites_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            # Remove old favorites buttons from all_emoji_buttons
            nonlocal all_emoji_buttons
            all_emoji_buttons = [(b, e, c, l, g) for b, e, c, l, g in all_emoji_buttons if c != 'favorites']

            # Add label
            fav_label = QLabel('⭐ Favorites')
            fav_label.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {section_header_color}; padding-top: 4px;")
            favorites_layout.addWidget(fav_label)

            if self.emoji_favorites:
                fav_grid = QWidget()
                fav_grid.setStyleSheet(f"background-color: {scroll_bg};")
                fav_grid_layout = QGridLayout(fav_grid)
                fav_grid_layout.setSpacing(2)
                fav_grid_layout.setContentsMargins(0, 0, 0, 0)

                for i, fav_em in enumerate(self.emoji_favorites):
                    row = i // EMOJIS_PER_ROW
                    col = i % EMOJIS_PER_ROW

                    # Check if this is a custom emoji (starts with "custom:")
                    if fav_em.startswith('custom:'):
                        custom_name = fav_em[7:]  # Remove "custom:" prefix
                        custom_data = next((ce for ce in self.custom_emojis if ce.get('name') == custom_name), None)
                        if custom_data:
                            btn = QPushButton()
                            btn.setObjectName("emojiBtn")
                            btn.setFixedSize(40, 40)
                            btn.setCursor(Qt.PointingHandCursor)
                            img_path = Path(main_window.custom_emojis_dir) / custom_data.get('filename', '')
                            if img_path.exists():
                                pixmap = QPixmap(str(img_path)).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                btn.setIcon(QIcon(pixmap))
                                btn.setIconSize(pixmap.size())
                            else:
                                btn.setText("?")
                            btn.clicked.connect(lambda checked, ce=custom_data: self._insert_custom_emoji(ce, dialog, main_window))
                            btn.setContextMenuPolicy(Qt.CustomContextMenu)
                            btn.customContextMenuRequested.connect(
                                lambda pos, b=btn, e=fav_em: show_emoji_context_menu(b, e)
                            )
                            fav_grid_layout.addWidget(btn, row, col)
                            all_emoji_buttons.append((btn, fav_em, 'favorites', fav_label, fav_grid))
                    else:
                        # Regular emoji
                        btn = QPushButton(fav_em)
                        btn.setObjectName("emojiBtn")
                        btn.setFixedSize(40, 40)
                        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                        btn.setFont(emoji_font)
                        btn.setCursor(Qt.PointingHandCursor)
                        btn.clicked.connect(lambda checked, e=fav_em: self._insert_emoji(e, dialog, main_window))
                        btn.setContextMenuPolicy(Qt.CustomContextMenu)
                        btn.customContextMenuRequested.connect(
                            lambda pos, b=btn, e=fav_em: show_emoji_context_menu(b, e)
                        )
                        fav_grid_layout.addWidget(btn, row, col)
                        all_emoji_buttons.append((btn, fav_em, 'favorites', fav_label, fav_grid))

                favorites_layout.addWidget(fav_grid)
                section_widgets['favorites'] = (fav_label, fav_grid)
            else:
                empty_label = QLabel("Right-click any emoji to add it to favorites")
                empty_label.setStyleSheet(f"color: {section_header_color}; font-style: italic; padding: 12px;")
                favorites_layout.addWidget(empty_label)
                section_widgets['favorites'] = (fav_label, empty_label)

        # Helper to toggle favorite status
        def toggle_favorite(emoji_id):
            """Toggle favorite status. emoji_id is either an emoji char or 'custom:name'"""
            if emoji_id in self.emoji_favorites:
                self.emoji_favorites.remove(emoji_id)
            else:
                self.emoji_favorites.append(emoji_id)
            main_window.save_emoji_favorites(self.emoji_favorites)
            # Rebuild favorites section in-place
            rebuild_favorites_section()

        # Helper to show emoji context menu
        def show_emoji_context_menu(button, emoji_id):
            """Show context menu. emoji_id is either an emoji char or 'custom:name'"""
            menu = QMenu(dialog)
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {input_bg};
                    color: {text_color};
                    border: 1px solid {input_border};
                    padding: 4px;
                }}
                QMenu::item {{
                    padding: 6px 20px;
                }}
                QMenu::item:selected {{
                    background-color: #FF6B00;
                    color: white;
                }}
            """)
            if emoji_id in self.emoji_favorites:
                action = menu.addAction("⭐ Remove from Favorites")
            else:
                action = menu.addAction("⭐ Add to Favorites")
            action.triggered.connect(lambda: toggle_favorite(emoji_id))
            menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))

        def create_emoji_section(cat_id, cat_name, emojis_list):
            """Create a section with label and emoji grid"""
            section_label = QLabel(cat_name)
            section_label.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {section_header_color}; padding-top: 4px;")
            emoji_main_layout.addWidget(section_label)

            grid_widget = QWidget()
            grid_widget.setStyleSheet(f"background-color: {scroll_bg};")
            grid_layout = QGridLayout(grid_widget)
            grid_layout.setSpacing(2)
            grid_layout.setContentsMargins(0, 0, 0, 0)

            for i, em in enumerate(emojis_list):
                row = i // EMOJIS_PER_ROW
                col = i % EMOJIS_PER_ROW

                btn = QPushButton(em)
                btn.setObjectName("emojiBtn")
                btn.setFixedSize(40, 40)
                btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                btn.setFont(emoji_font)
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda checked, e=em: self._insert_emoji(e, dialog, main_window))
                # Add right-click context menu for favorites
                btn.setContextMenuPolicy(Qt.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, b=btn, e=em: show_emoji_context_menu(b, e)
                )
                grid_layout.addWidget(btn, row, col)
                all_emoji_buttons.append((btn, em, cat_id, section_label, grid_widget))

            emoji_main_layout.addWidget(grid_widget)
            section_widgets[cat_id] = (section_label, grid_widget)

        # Add Favorites section container
        emoji_main_layout.addWidget(favorites_container)
        rebuild_favorites_section()

        # Add emoji sections from database
        for cat_id, cat_icon, cat_name in self.emoji_categories:
            if cat_id in ('favorites', 'custom'):
                continue  # Skip - handled separately
            emojis_list = self.emoji_database.get(cat_id, [])
            if emojis_list:
                create_emoji_section(cat_id, cat_name, emojis_list)

        # Add Custom section
        custom_section_label = QLabel('Custom')
        custom_section_label.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {section_header_color}; padding-top: 4px;")
        emoji_main_layout.addWidget(custom_section_label)

        if self.custom_emojis:
            custom_grid = QWidget()
            custom_grid.setStyleSheet(f"background-color: {scroll_bg};")
            custom_layout = QGridLayout(custom_grid)
            custom_layout.setSpacing(2)
            custom_layout.setContentsMargins(0, 0, 0, 0)

            def delete_custom_emoji(emoji_to_delete):
                """Delete a custom emoji"""
                name = emoji_to_delete.get('name', '')
                reply = QMessageBox.question(
                    dialog, "Delete Custom Emoji",
                    f"Delete custom emoji :{name}:?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    # Remove from favorites if present
                    fav_key = f"custom:{name}"
                    if fav_key in self.emoji_favorites:
                        self.emoji_favorites.remove(fav_key)
                        main_window.save_emoji_favorites(self.emoji_favorites)
                    # Remove from list
                    self.custom_emojis = [e for e in self.custom_emojis if e.get('name') != name]
                    main_window.save_custom_emojis(self.custom_emojis)
                    # Delete file
                    filename = emoji_to_delete.get('filename', '')
                    file_path = Path(main_window.custom_emojis_dir) / filename
                    if file_path.exists():
                        file_path.unlink()
                    # Refresh dialog
                    dialog.reject()
                    self.show_emoji_picker()

            def show_custom_emoji_context_menu(button, custom_emoji):
                """Show context menu for custom emoji with favorite and delete options"""
                menu = QMenu(dialog)
                menu.setStyleSheet(f"""
                    QMenu {{
                        background-color: {input_bg};
                        color: {text_color};
                        border: 1px solid {input_border};
                        padding: 4px;
                    }}
                    QMenu::item {{
                        padding: 6px 20px;
                    }}
                    QMenu::item:selected {{
                        background-color: #FF6B00;
                        color: white;
                    }}
                """)
                name = custom_emoji.get('name', '')
                emoji_id = f"custom:{name}"

                # Favorite action
                if emoji_id in self.emoji_favorites:
                    fav_action = menu.addAction("⭐ Remove from Favorites")
                else:
                    fav_action = menu.addAction("⭐ Add to Favorites")
                fav_action.triggered.connect(lambda: toggle_favorite(emoji_id))

                menu.addSeparator()

                # Delete action
                del_action = menu.addAction("🗑️ Delete Custom Emoji")
                del_action.triggered.connect(lambda: delete_custom_emoji(custom_emoji))

                menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))

            for i, custom_em in enumerate(self.custom_emojis):
                row = i // EMOJIS_PER_ROW
                col = i % EMOJIS_PER_ROW

                btn = QPushButton()
                btn.setObjectName("emojiBtn")
                btn.setFixedSize(40, 40)
                btn.setCursor(Qt.PointingHandCursor)

                # Load custom emoji image
                img_path = Path(main_window.custom_emojis_dir) / custom_em.get('filename', '')
                if img_path.exists():
                    pixmap = QPixmap(str(img_path)).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    btn.setIcon(QIcon(pixmap))
                    btn.setIconSize(pixmap.size())
                else:
                    btn.setText("?")

                btn.setToolTip(f":{custom_em.get('name', 'custom')}: (right-click for options)")
                btn.clicked.connect(lambda checked, ce=custom_em: self._insert_custom_emoji(ce, dialog, main_window))

                # Add right-click context menu for favorites and deletion
                btn.setContextMenuPolicy(Qt.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, ce=custom_em, b=btn: show_custom_emoji_context_menu(b, ce)
                )

                custom_layout.addWidget(btn, row, col)
                all_emoji_buttons.append((btn, f"custom:{custom_em.get('name', '')}", 'custom', custom_section_label, custom_grid))

            emoji_main_layout.addWidget(custom_grid)
            section_widgets['custom'] = (custom_section_label, custom_grid)
        else:
            empty_label = QLabel("Add custom emojis with the button below")
            empty_label.setStyleSheet(f"color: {section_header_color}; font-style: italic; padding: 12px;")
            emoji_main_layout.addWidget(empty_label)
            section_widgets['custom'] = (custom_section_label, empty_label)

        emoji_main_layout.addStretch()
        scroll.setWidget(emoji_container)
        layout.addWidget(scroll)

        # Add Custom Emoji button
        add_layout = QHBoxLayout()
        add_layout.addStretch()
        add_emoji_btn = QPushButton("+ Add Custom Emoji")
        add_emoji_btn.setObjectName("addEmojiBtn")
        add_emoji_btn.setCursor(Qt.PointingHandCursor)
        add_emoji_btn.clicked.connect(lambda: self._show_add_custom_emoji_dialog(dialog, main_window))
        add_layout.addWidget(add_emoji_btn)
        add_layout.addStretch()
        layout.addLayout(add_layout)

        # Connect category tabs to scroll to sections
        def scroll_to_category(cat_id):
            for btn_cat_id, btn in category_buttons:
                btn.setChecked(btn_cat_id == cat_id)
            if cat_id in section_widgets:
                label, widget = section_widgets[cat_id]
                scroll.ensureWidgetVisible(label)

        for cat_id, tab_btn in category_buttons:
            tab_btn.clicked.connect(lambda checked, cid=cat_id: scroll_to_category(cid))

        # Select first tab by default
        if category_buttons:
            category_buttons[0][1].setChecked(True)

        # Search filtering with name-based lookup
        def filter_emojis(text):
            text = text.lower().strip()

            if not text:
                # Show all emojis
                for btn, em, cat_id, label, grid in all_emoji_buttons:
                    btn.show()
                for cat_id, (label, widget) in section_widgets.items():
                    label.show()
                    widget.show()
                return

            # Find matching emojis from search index
            matching_emojis = set()
            for term, emojis_set in self.emoji_search_index.items():
                if text in term:
                    matching_emojis.update(emojis_set)

            # Also match custom emojis by name
            for custom_em in self.custom_emojis:
                if text in custom_em.get('name', '').lower():
                    matching_emojis.add(f"custom:{custom_em.get('name', '')}")

            # Show/hide buttons
            visible_categories = set()
            for btn, em, cat_id, label, grid in all_emoji_buttons:
                if em in matching_emojis:
                    btn.show()
                    visible_categories.add(cat_id)
                else:
                    btn.hide()

            # Show/hide category sections
            for cat_id, (label, widget) in section_widgets.items():
                if cat_id in visible_categories:
                    label.show()
                    widget.show()
                else:
                    label.hide()
                    widget.hide()

        search_input.textChanged.connect(filter_emojis)

        dialog.exec_()

    def _insert_emoji(self, emoji_char, dialog, main_window):
        """Insert emoji and close dialog"""
        self.insert_variable(emoji_char)
        dialog.accept()

    def _insert_custom_emoji(self, custom_emoji, dialog, main_window):
        """Insert custom emoji as image or shortcode"""
        insert_mode = custom_emoji.get('insert_mode', 'shortcode')
        name = custom_emoji.get('name', 'custom')
        filename = custom_emoji.get('filename', '')
        img_path = Path(main_window.custom_emojis_dir) / filename

        # Close dialog first to avoid UI issues
        dialog.accept()

        if insert_mode == 'shortcode' or not img_path.exists():
            # Insert as :name: text
            self.insert_variable(f":{name}:")
        else:
            # Insert as embedded image in the QTextEdit
            cursor = self.content_input.textCursor()
            image = QImage(str(img_path))
            if not image.isNull():
                # Scale to reasonable emoji size (24x24)
                scaled = image.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                cursor.insertImage(scaled)
            else:
                # Fallback to shortcode if image can't be loaded
                self.insert_variable(f":{name}:")
            self.content_input.setFocus()

    def _show_add_custom_emoji_dialog(self, parent_dialog, main_window):
        """Show dialog to add a custom emoji"""
        dialog = QDialog(parent_dialog)
        dialog.setWindowTitle("Add Custom Emoji")
        dialog.setMinimumSize(400, 300)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)

        if self.is_light_theme:
            dialog.setStyleSheet("""
                QDialog { background-color: #F5F5F5; }
                QLabel { color: #212121; }
                QLineEdit { background-color: #FFFFFF; color: #212121; border: 1px solid #BDBDBD; padding: 8px; border-radius: 4px; }
                QLineEdit:focus { border-color: #FF6B00; }
                QPushButton { background-color: #FF6B00; color: white; border: none; border-radius: 4px; padding: 8px 16px; }
                QPushButton:hover { background-color: #FF8C00; }
                QPushButton#browseBtn { background-color: #757575; }
                QPushButton#browseBtn:hover { background-color: #616161; }
                QRadioButton { color: #212121; }
            """)
        else:
            dialog.setStyleSheet("""
                QDialog { background-color: #1E1E1E; }
                QLabel { color: #E0E0E0; }
                QLineEdit { background-color: #2A2A2A; color: #E0E0E0; border: 1px solid #424242; padding: 8px; border-radius: 4px; }
                QLineEdit:focus { border-color: #FF6B00; }
                QPushButton { background-color: #FF6B00; color: white; border: none; border-radius: 4px; padding: 8px 16px; }
                QPushButton:hover { background-color: #FF8C00; }
                QPushButton#browseBtn { background-color: #424242; }
                QPushButton#browseBtn:hover { background-color: #555555; }
                QRadioButton { color: #E0E0E0; }
            """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(16)

        # File selection
        file_layout = QHBoxLayout()
        file_label = QLabel("Image:")
        file_input = QLineEdit()
        file_input.setPlaceholderText("Select PNG or GIF file...")
        file_input.setReadOnly(True)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("browseBtn")
        file_layout.addWidget(file_label)
        file_layout.addWidget(file_input, 1)
        file_layout.addWidget(browse_btn)
        layout.addLayout(file_layout)

        # Preview
        preview_label = QLabel("Preview:")
        layout.addWidget(preview_label)

        preview_frame = QFrame()
        preview_frame.setFixedSize(80, 80)
        preview_frame.setStyleSheet("border: 1px solid #424242; border-radius: 4px;")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        preview_image = QLabel()
        preview_image.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(preview_image)
        layout.addWidget(preview_frame)

        # Name input
        name_layout = QHBoxLayout()
        name_label = QLabel("Name:")
        name_input = QLineEdit()
        name_input.setPlaceholderText("emoji_name (becomes :emoji_name:)")
        name_layout.addWidget(name_label)
        name_layout.addWidget(name_input, 1)
        layout.addLayout(name_layout)

        # Insert mode
        from PyQt5.QtWidgets import QRadioButton, QButtonGroup
        mode_label = QLabel("Default insert mode:")
        layout.addWidget(mode_label)

        mode_group = QButtonGroup(dialog)
        image_radio = QRadioButton("As image (paste into content)")
        shortcode_radio = QRadioButton("As shortcode (:name:)")
        mode_group.addButton(image_radio, 0)
        mode_group.addButton(shortcode_radio, 1)
        image_radio.setChecked(True)
        layout.addWidget(image_radio)
        layout.addWidget(shortcode_radio)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background-color: #757575;")
        cancel_btn.clicked.connect(dialog.reject)
        save_btn = QPushButton("Add Emoji")
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        selected_file = [None]  # Use list to allow modification in nested function

        def browse_file():
            file_path, _ = QFileDialog.getOpenFileName(
                dialog, "Select Emoji Image",
                str(Path.home()),
                "Images (*.png *.gif *.PNG *.GIF *.jpg *.jpeg *.JPG *.JPEG)"
            )
            if file_path:
                selected_file[0] = file_path
                file_input.setText(Path(file_path).name)

                # Update preview
                pixmap = QPixmap(file_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                preview_image.setPixmap(pixmap)

                # Auto-fill name from filename
                if not name_input.text():
                    stem = Path(file_path).stem.lower()
                    # Clean up name: remove special chars, replace spaces
                    clean_name = re.sub(r'[^a-z0-9_]', '_', stem)
                    clean_name = re.sub(r'_+', '_', clean_name).strip('_')
                    name_input.setText(clean_name)

        browse_btn.clicked.connect(browse_file)

        def save_emoji():
            if not selected_file[0]:
                QMessageBox.warning(dialog, "No File", "Please select an image file.")
                return

            name = name_input.text().strip().lower()
            if not name:
                QMessageBox.warning(dialog, "No Name", "Please enter a name for the emoji.")
                return

            # Validate name (alphanumeric and underscores only)
            if not re.match(r'^[a-z0-9_]+$', name):
                QMessageBox.warning(dialog, "Invalid Name", "Name can only contain lowercase letters, numbers, and underscores.")
                return

            # Check for duplicate names
            for existing in self.custom_emojis:
                if existing.get('name') == name:
                    QMessageBox.warning(dialog, "Duplicate Name", f"An emoji named ':{name}:' already exists.")
                    return

            # Process and save image (auto-resize if needed)
            src_path = Path(selected_file[0])
            filename = f"{name}.png"  # Always save as PNG for consistency
            dest_path = main_window.custom_emojis_dir / filename

            try:
                # Open with PIL and resize if needed
                img = Image.open(src_path)

                # Convert to RGBA for PNG compatibility
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')

                # Resize if larger than 128x128 (good size for emoji)
                max_size = 128
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), Image.LANCZOS)

                # Save as PNG
                img.save(dest_path, 'PNG', optimize=True)
            except Exception as e:
                QMessageBox.warning(dialog, "Image Error", f"Could not process image: {str(e)}")
                return

            # Add to custom emojis list
            new_emoji = {
                'name': name,
                'filename': filename,
                'insert_mode': 'shortcode' if shortcode_radio.isChecked() else 'image'
            }
            self.custom_emojis.append(new_emoji)
            main_window.save_custom_emojis(self.custom_emojis)

            dialog.accept()
            # Close and reopen parent dialog to refresh
            parent_dialog.reject()
            self.show_emoji_picker()

        save_btn.clicked.connect(save_emoji)

        dialog.exec_()

    def show_find_replace(self):
        """Show find and replace dialog"""
        main_window = self.window()
        dialog = QDialog(main_window)
        dialog.setWindowTitle("Find and Replace")
        dialog.setMinimumSize(400, 200)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        if self.is_light_theme:
            dialog.setStyleSheet("""
                QDialog { background-color: #F5F5F5; }
                QLabel { color: #212121; }
                QLineEdit { background-color: #FFFFFF; color: #212121; border: 1px solid #BDBDBD; padding: 6px; border-radius: 4px; }
                QLineEdit:focus { border-color: #FF6B00; }
                QPushButton { background-color: #FF6B00; color: white; border: none; border-radius: 4px; padding: 8px 16px; min-width: 80px; }
                QPushButton:hover { background-color: #FF8C00; }
                QCheckBox { color: #212121; }
                QCheckBox::indicator { width: 16px; height: 16px; }
            """)
        else:
            dialog.setStyleSheet("""
                QDialog { background-color: #1E1E1E; }
                QLabel { color: #E0E0E0; }
                QLineEdit { background-color: #2A2A2A; color: #E0E0E0; border: 1px solid #424242; padding: 6px; border-radius: 4px; }
                QLineEdit:focus { border-color: #FF6B00; }
                QPushButton { background-color: #FF6B00; color: white; border: none; border-radius: 4px; padding: 8px 16px; min-width: 80px; }
                QPushButton:hover { background-color: #FF8C00; }
                QCheckBox { color: #E0E0E0; }
                QCheckBox::indicator { width: 16px; height: 16px; }
            """)

        layout = QVBoxLayout(dialog)

        # Find field
        find_layout = QHBoxLayout()
        find_layout.addWidget(QLabel("Find:"))
        find_input = QLineEdit()
        find_layout.addWidget(find_input)
        layout.addLayout(find_layout)

        # Replace field
        replace_layout = QHBoxLayout()
        replace_layout.addWidget(QLabel("Replace:"))
        replace_input = QLineEdit()
        replace_layout.addWidget(replace_input)
        layout.addLayout(replace_layout)

        # Options
        options_layout = QHBoxLayout()
        case_cb = QCheckBox("Case sensitive")
        options_layout.addWidget(case_cb)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Status label
        status_label = QLabel("")
        status_label.setStyleSheet("QLabel { color: #888888; font-style: italic; }")
        layout.addWidget(status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        def find_next():
            text = find_input.text()
            if not text:
                return
            content = self.content_input.toPlainText()
            cursor = self.content_input.textCursor()
            start_pos = cursor.position()

            flags = 0 if case_cb.isChecked() else re.IGNORECASE
            pattern = re.compile(re.escape(text), flags)

            # Search from current position
            match = pattern.search(content, start_pos)
            if not match:
                # Wrap around to beginning
                match = pattern.search(content)

            if match:
                cursor.setPosition(match.start())
                cursor.setPosition(match.end(), cursor.KeepAnchor)
                self.content_input.setTextCursor(cursor)
                status_label.setText(f"Found at position {match.start()}")
            else:
                status_label.setText("Not found")

        def replace_current():
            cursor = self.content_input.textCursor()
            if cursor.hasSelection():
                cursor.insertText(replace_input.text())
                find_next()

        def replace_all():
            text = find_input.text()
            replacement = replace_input.text()
            if not text:
                return
            content = self.content_input.toPlainText()
            flags = 0 if case_cb.isChecked() else re.IGNORECASE
            new_content, count = re.subn(re.escape(text), replacement, content, flags=flags)
            if count > 0:
                self.content_input.setPlainText(new_content)
                status_label.setText(f"Replaced {count} occurrence(s)")
            else:
                status_label.setText("No matches found")

        find_btn = QPushButton("Find Next")
        find_btn.clicked.connect(find_next)
        btn_layout.addWidget(find_btn)

        replace_btn = QPushButton("Replace")
        replace_btn.clicked.connect(replace_current)
        btn_layout.addWidget(replace_btn)

        replace_all_btn = QPushButton("Replace All")
        replace_all_btn.clicked.connect(replace_all)
        btn_layout.addWidget(replace_all_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setStyleSheet(self.get_cancel_btn_stylesheet())
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        dialog.exec_()

    def insert_today_date(self):
        """Insert dynamic date variable (resolves at expansion time)"""
        self.insert_variable('{{date}}')

    def insert_current_time(self):
        """Insert dynamic time variable (resolves at expansion time)"""
        self.insert_variable('{{time}}')

    def show_calendar_dialog(self):
        """Show calendar dialog to select a date"""
        main_window = self.window()
        dialog = QDialog(main_window)
        dialog.setWindowTitle("Select Date")
        dialog.setMinimumSize(350, 300)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #121212;
            }
            QCalendarWidget {
                background-color: #1E1E1E;
                color: #E0E0E0;
            }
            QCalendarWidget QToolButton {
                color: #E0E0E0;
                background-color: #2A2A2A;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QCalendarWidget QToolButton:hover {
                background-color: #3A3A3A;
            }
            QCalendarWidget QMenu {
                background-color: #1E1E1E;
                color: #E0E0E0;
            }
            QCalendarWidget QSpinBox {
                background-color: #2A2A2A;
                color: #E0E0E0;
                border: 1px solid #424242;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: #2A2A2A;
            }
            QCalendarWidget QAbstractItemView:enabled {
                background-color: #1E1E1E;
                color: #E0E0E0;
                selection-background-color: #FF6B00;
                selection-color: white;
            }
            QCalendarWidget QAbstractItemView:disabled {
                color: #555555;
            }
        """)

        layout = QVBoxLayout(dialog)

        calendar = QCalendarWidget()
        calendar.setGridVisible(True)
        layout.addWidget(calendar)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        button_box.setStyleSheet("""
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
        """)
        layout.addWidget(button_box)

        if dialog.exec_() == QDialog.Accepted:
            selected_date = calendar.selectedDate().toString("MM-dd-yyyy")
            self.insert_variable(selected_date)

    def insert_text_field_dialog(self):
        """Prompt for text field name and insert it"""
        name, ok = self.get_text_input('Text Field', 'Enter field name:')
        if ok and name:
            self.insert_variable('{{' + name.strip() + '}}')

    def insert_dropdown_dialog(self):
        """Prompt for dropdown field name and options"""
        name, ok = self.get_text_input('Dropdown Menu', 'Enter field name:')
        if ok and name:
            options, ok2 = self.get_text_input('Dropdown Options',
                                               'Enter options separated by | (e.g., Low|Medium|High):')
            if ok2 and options:
                self.insert_variable('{{' + name.strip() + '=' + options.strip() + '}}')

    def insert_toggle_dialog(self):
        """Prompt for toggle section name and insert start/end tags"""
        name, ok = self.get_text_input('Toggle Section', 'Enter section name (e.g., "Mobile Phone"):')
        if ok and name:
            name = name.strip()
            # Insert both opening and closing tags with cursor in between
            cursor = self.content_input.textCursor()
            cursor.insertText('{{' + name + ':toggle}}')
            cursor.insertText('{{/' + name + ':toggle}}')
            # Move cursor back to between the tags
            cursor.movePosition(cursor.Left, cursor.MoveAnchor, len('{{/' + name + ':toggle}}'))
            self.content_input.setTextCursor(cursor)
            self.content_input.setFocus()

    def insert_multi_select_dialog(self):
        """Prompt for multi-select field name and options"""
        name, ok = self.get_text_input('Multiple Selection', 'Enter field name:')
        if ok and name:
            options, ok2 = self.get_text_input('Selection Options',
                                               'Enter options separated by | (e.g., Red|Green|Blue):')
            if ok2 and options:
                self.insert_variable('{{' + name.strip() + ':multi=' + options.strip() + '}}')

    def insert_date_picker_dialog(self):
        """Prompt for date picker field name and insert it"""
        name, ok = self.get_text_input('Date Picker', 'Enter field name (e.g., "Start Date"):')
        if ok and name:
            self.insert_variable('{{' + name.strip() + ':date}}')

    def insert_calculation_dialog(self):
        """Show dialog to create a dynamic calculation"""
        main_window = self.window()
        dialog = QDialog(main_window)
        dialog.setWindowTitle('Insert Calculation')
        dialog.setMinimumWidth(400)
        dialog.setMinimumHeight(300)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)

        # Get theme
        is_light = self.is_light_theme
        bg_color = '#FFFFFF' if is_light else '#1E1E1E'
        dialog.setStyleSheet(f"QDialog {{ background-color: {bg_color}; }}")

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Instructions
        text_color = '#424242' if is_light else '#E0E0E0'
        text_color = '#424242' if is_light else '#E0E0E0'
        instructions = QLabel(f"""<span style="color: {text_color};">
            <b>Create a calculation expression:</b><br><br>
            <b>Operators:</b> + - * / % ^ ( )<br>
            <b>Functions:</b> round, floor, ceil, abs, min, max<br>
            <b>Reference fields:</b> Use field names from your snippet<br><br>
            <b>Examples:</b><br>
            • <code>price * quantity</code><br>
            • <code>subtotal * 1.08</code> (add 8% tax)<br>
            • <code>round(total / 12, 2)</code> (monthly payment)<br>
            • <code>(hours * rate) + bonus</code>
            </span>""")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Expression input
        expr_label = QLabel("Expression:")
        expr_label.setStyleSheet(f"color: {text_color}; font-weight: bold;")
        layout.addWidget(expr_label)

        expr_input = QLineEdit()
        expr_input.setPlaceholderText("e.g., price * quantity * 1.08")
        expr_input.setStyleSheet(f"""
            QLineEdit {{
                padding: 8px;
                border: 1px solid {'#BDBDBD' if is_light else '#555555'};
                border-radius: 4px;
                background-color: {'#FFFFFF' if is_light else '#2A2A2A'};
                color: {text_color};
            }}
        """)
        layout.addWidget(expr_input)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                padding: 8px 20px;
                border: 1px solid {'#BDBDBD' if is_light else '#555555'};
                border-radius: 4px;
                background-color: {'#F5F5F5' if is_light else '#3A3A3A'};
                color: {text_color};
            }}
            QPushButton:hover {{
                background-color: {'#E0E0E0' if is_light else '#4A4A4A'};
            }}
        """)
        btn_layout.addWidget(cancel_btn)

        insert_btn = QPushButton("Insert")
        insert_btn.clicked.connect(dialog.accept)
        insert_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 20px;
                border: none;
                border-radius: 4px;
                background-color: #FF6B00;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FF8533;
            }
        """)
        btn_layout.addWidget(insert_btn)

        layout.addLayout(btn_layout)

        if dialog.exec_() == QDialog.Accepted:
            expr = expr_input.text().strip()
            if expr:
                self.insert_variable('{{calc:' + expr + '}}')

    def set_snippets(self, snippets):
        """Set the snippets list for Insert Snippet feature"""
        self.snippets_list = snippets

    def insert_snippet_dialog(self):
        """Show dialog to select a snippet to embed"""
        if not self.snippets_list:
            QMessageBox.information(self, 'No Snippets', 'No snippets available to insert.')
            return

        # Create a list of snippet options (trigger - description)
        snippet_options = []
        for s in self.snippets_list:
            trigger = s.get('trigger', '')
            desc = s.get('description', '')
            if trigger:
                display = f"{trigger} - {desc}" if desc else trigger
                snippet_options.append((display, trigger))

        if not snippet_options:
            QMessageBox.information(self, 'No Snippets', 'No snippets with triggers available.')
            return

        # Show selection dialog
        items = [opt[0] for opt in snippet_options]
        item, ok = self.get_item_input('Insert Snippet',
                                       'Select snippet to embed:', items, 0, False)
        if ok and item:
            # Find the trigger for the selected item
            for display, trigger in snippet_options:
                if display == item:
                    self.insert_variable('{{snippet:' + trigger + '}}')
                    break

    def get_snippet(self):
        """Return the snippet data"""
        folder = self.folder_combo.currentText().strip()
        if not folder:
            folder = 'General'
        data = {
            'folder': folder,
            'trigger': self.trigger_input.text(),
            'description': self.desc_input.text(),
            'type': 'universal',
            'content': self.content_input.toPlainText()
        }
        # Include rich HTML if available (for tables, formatting, etc.)
        if self.content_input.hasRichContent():
            data['rich_html'] = self.content_input.getRichHtml()
        return data

    def on_save(self):
        """Handle save button click"""
        snippet = self.get_snippet()
        if snippet['trigger']:
            self.save_requested.emit(snippet)

    def on_cancel(self):
        """Handle cancel/back button click"""
        self.cancel_requested.emit()

    def show_preview(self):
        """Show a preview of the snippet with rendered form fields"""
        content = self.content_input.toPlainText()
        trigger = self.trigger_input.text()

        main_window = self.window()
        dialog = QDialog(main_window)
        dialog.setWindowTitle("Snippet Preview")
        dialog.setMinimumSize(600, 400)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #121212;
            }
            QLabel {
                color: #E0E0E0;
            }
        """)

        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Header with trigger
        header_layout = QHBoxLayout()
        trigger_label = QLabel(f"Trigger: ")
        trigger_label.setStyleSheet("color: #757575;")
        trigger_chip = QLabel(trigger if trigger else "(no trigger)")
        trigger_chip.setStyleSheet("""
            QLabel {
                background-color: #2A2A2A;
                color: #FF6B00;
                padding: 4px 12px;
                border-radius: 12px;
                font-weight: bold;
            }
        """)
        header_layout.addWidget(trigger_label)
        header_layout.addWidget(trigger_chip)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # Scroll area for preview content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #333333;
                border-radius: 8px;
                background-color: #1E1E1E;
            }
        """)

        # Preview content widget
        preview_widget = QWidget()
        preview_widget.setStyleSheet("background-color: #1E1E1E;")
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(16, 16, 16, 16)

        # Build the preview with inline form elements
        self.build_preview_content(preview_layout, content)

        scroll.setWidget(preview_widget)
        main_layout.addWidget(scroll)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 24px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
        """)
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_layout.addWidget(close_btn)
        main_layout.addLayout(close_layout)

        dialog.exec_()

    def build_preview_content(self, layout, content):
        """Build preview content with rendered form fields inline"""
        import re

        # Process toggle sections first - these can span multiple lines
        self._build_preview_recursive(layout, content)

    def _build_preview_recursive(self, layout, content):
        """Recursively build preview, handling toggle sections"""
        import re

        # Pattern for toggle sections: {{name:toggle}}...{{/name:toggle}}
        toggle_pattern = r'\{\{([^}:]+):toggle\}\}(.*?)\{\{/\1:toggle\}\}'

        # Find the first toggle section
        match = re.search(toggle_pattern, content, re.DOTALL)

        if match:
            # Content before the toggle
            before_content = content[:match.start()]
            if before_content:
                self._build_preview_lines(layout, before_content)

            # The toggle section
            toggle_name = match.group(1).strip()
            toggle_content = match.group(2)

            # Create toggle section preview
            toggle_container = QWidget()
            toggle_layout = QVBoxLayout(toggle_container)
            toggle_layout.setContentsMargins(0, 4, 0, 4)
            toggle_layout.setSpacing(2)

            # Checkbox row
            checkbox_row = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_row)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)

            checkbox = QCheckBox(toggle_name)
            checkbox.setChecked(True)
            checkbox.setStyleSheet("""
                QCheckBox {
                    color: #E0E0E0;
                    font-weight: 500;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border: 2px solid #4A90D9;
                    border-radius: 3px;
                    background-color: #1E1E1E;
                }
                QCheckBox::indicator:checked {
                    background-color: #4A90D9;
                }
            """)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.addStretch()
            toggle_layout.addWidget(checkbox_row)

            # Content container (indented)
            content_container = QWidget()
            content_layout = QVBoxLayout(content_container)
            content_layout.setContentsMargins(26, 0, 0, 0)
            content_layout.setSpacing(2)

            self._build_preview_lines(content_layout, toggle_content)
            toggle_layout.addWidget(content_container)

            layout.addWidget(toggle_container)

            # Content after the toggle
            after_content = content[match.end():]
            if after_content:
                self._build_preview_recursive(layout, after_content)
        else:
            # No more toggle sections
            self._build_preview_lines(layout, content)

    def _build_preview_lines(self, layout, content):
        """Build preview lines with inline form fields"""
        import re

        def convert_formatting_to_html(text):
            """Convert formatting markers to HTML for preview display"""
            # Convert bold: **text** -> <b>text</b>
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
            # Convert italic: *text* -> <i>text</i>
            text = re.sub(r'(?<![*<])\*([^*]+?)\*(?![*>])', r'<i>\1</i>', text)
            # <u>text</u> is already HTML
            return text

        # Define patterns for different variable types (excluding toggle)
        patterns = [
            (r'\{\{snippet:([^}]+)\}\}', 'snippet'),
            (r'\{\{calc:([^}]+)\}\}', 'calc'),
            (r'\{\{([^}:]+):multi=([^}]+)\}\}', 'multi'),
            (r'\{\{([^}:]+):date\}\}', 'date_picker'),
            (r'\{\{date([+-])(\d+)\}\}', 'date_arith'),
            (r'\{\{(date)\}\}', 'date_var'),
            (r'\{\{(time)\}\}', 'time_var'),
            (r'\{\{(datetime)\}\}', 'datetime_var'),
            (r'\{\{(clipboard)\}\}', 'clipboard_var'),
            (r'\{\{(cursor)\}\}', 'cursor_var'),
            (r'\{\{([^}=:]+)=([^}]+)\}\}', 'dropdown'),
            (r'\{\{([^}=:/]+)\}\}', 'text'),
        ]

        # Split content into lines for processing
        lines = content.split('\n')

        for line in lines:
            line_widget = QWidget()
            line_layout = QHBoxLayout(line_widget)
            line_layout.setContentsMargins(0, 2, 0, 2)
            line_layout.setSpacing(0)

            remaining = line
            while remaining:
                earliest_match = None
                earliest_pos = len(remaining)
                match_type = None
                match_groups = None

                for pattern, var_type in patterns:
                    match = re.search(pattern, remaining)
                    if match and match.start() < earliest_pos:
                        earliest_match = match
                        earliest_pos = match.start()
                        match_type = var_type
                        match_groups = match.groups()

                if earliest_match:
                    if earliest_pos > 0:
                        # Convert formatting and use rich text label
                        html_text = convert_formatting_to_html(remaining[:earliest_pos])
                        text_label = QLabel(html_text)
                        text_label.setTextFormat(Qt.RichText)
                        text_label.setStyleSheet("color: #E0E0E0; background: transparent;")
                        line_layout.addWidget(text_label)

                    field_widget = self.create_preview_field(match_type, match_groups)
                    line_layout.addWidget(field_widget)

                    remaining = remaining[earliest_match.end():]
                else:
                    if remaining:
                        # Convert formatting and use rich text label
                        html_text = convert_formatting_to_html(remaining)
                        text_label = QLabel(html_text)
                        text_label.setTextFormat(Qt.RichText)
                        text_label.setStyleSheet("color: #E0E0E0; background: transparent;")
                        line_layout.addWidget(text_label)
                    remaining = ""

            line_layout.addStretch()
            layout.addWidget(line_widget)

        layout.addStretch()

    def create_preview_field(self, field_type, groups):
        """Create a preview widget for a form field"""
        if field_type == 'snippet':
            trigger = groups[0]
            # Find snippet description for display
            desc = trigger
            for s in self.snippets_list:
                if s.get('trigger', '') == trigger:
                    desc = s.get('description', '') or trigger
                    break
            label = QLabel(f"[{desc}]")
            label.setStyleSheet("""
                QLabel {
                    background-color: #E8EAF6;
                    color: #3F51B5;
                    border: 1px solid #7986CB;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: 500;
                }
            """)
            return label

        elif field_type == 'text':
            name = groups[0]
            field = QLineEdit()
            field.setPlaceholderText(name)
            field.setStyleSheet("""
                QLineEdit {
                    background-color: #FFFDE7;
                    color: #333333;
                    border: 1px solid #FDD835;
                    border-radius: 3px;
                    padding: 2px 6px;
                    min-width: 120px;
                    max-width: 200px;
                }
            """)
            return field

        elif field_type == 'dropdown':
            name, options = groups
            combo = QComboBox()
            combo.addItems([opt.strip() for opt in options.split('|')])
            combo.setStyleSheet("""
                QComboBox {
                    background-color: #FFFDE7;
                    color: #333333;
                    border: 1px solid #FDD835;
                    border-radius: 3px;
                    padding: 2px 6px;
                    min-width: 100px;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox QAbstractItemView {
                    background-color: #FFFDE7;
                    color: #333333;
                    selection-background-color: #FDD835;
                }
            """)
            return combo

        elif field_type == 'multi':
            name, options = groups
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(8)
            for opt in options.split('|'):
                cb = QCheckBox(opt.strip())
                cb.setStyleSheet("""
                    QCheckBox {
                        color: #E0E0E0;
                        spacing: 4px;
                    }
                    QCheckBox::indicator {
                        width: 14px;
                        height: 14px;
                        border: 2px solid #4A90D9;
                        border-radius: 3px;
                        background-color: #1E1E1E;
                    }
                    QCheckBox::indicator:checked {
                        background-color: #4A90D9;
                    }
                """)
                container_layout.addWidget(cb)
            return container

        elif field_type == 'date_picker':
            name = groups[0]
            date_edit = QDateEdit()
            date_edit.setDate(QDate.currentDate())
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("MM/dd/yyyy")
            date_edit.setStyleSheet("""
                QDateEdit {
                    background-color: #FFFDE7;
                    color: #333333;
                    border: 1px solid #FDD835;
                    border-radius: 3px;
                    padding: 2px 6px;
                    min-width: 110px;
                }
                QDateEdit::drop-down {
                    border: none;
                    width: 20px;
                }
            """)
            return date_edit

        elif field_type == 'date_arith':
            from datetime import timedelta
            operator, days = groups
            days = int(days)
            if operator == '-':
                days = -days
            result_date = datetime.now() + timedelta(days=days)
            label = QLabel(result_date.strftime(self.date_format_getter()))
            label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    border: 1px solid #64B5F6;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: 500;
                }
            """)
            return label

        elif field_type == 'date_var':
            label = QLabel(datetime.now().strftime(self.date_format_getter()))
            label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    border: 1px solid #64B5F6;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: 500;
                }
            """)
            return label

        elif field_type == 'time_var':
            label = QLabel(datetime.now().strftime(self.time_format_getter()))
            label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    border: 1px solid #64B5F6;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: 500;
                }
            """)
            return label

        elif field_type == 'datetime_var':
            label = QLabel(datetime.now().strftime(self.date_format_getter() + ' ' + self.time_format_getter()))
            label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    border: 1px solid #64B5F6;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: 500;
                }
            """)
            return label

        elif field_type == 'clipboard_var':
            label = QLabel("CLIPBOARD")
            label.setStyleSheet("""
                QLabel {
                    background-color: #F3E5F5;
                    color: #7B1FA2;
                    border: 1px solid #BA68C8;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: 500;
                    font-size: 10px;
                }
            """)
            return label

        elif field_type == 'cursor_var':
            label = QLabel("CURSOR")
            label.setStyleSheet("""
                QLabel {
                    background-color: #E8F5E9;
                    color: #2E7D32;
                    border: 1px solid #81C784;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: 500;
                    font-size: 10px;
                }
            """)
            return label

        elif field_type == 'calc':
            expr = groups[0]
            label = QLabel(f"= {expr}")
            label.setStyleSheet("""
                QLabel {
                    background-color: #FFF3E0;
                    color: #E65100;
                    border: 1px solid #FFB74D;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: 500;
                    font-family: monospace;
                }
            """)
            return label

        # Fallback
        return QLabel("")


class KeyboardListener(QThread):
    """Background thread to listen for keyboard input.
    Uses evdev on Linux (Wayland-compatible) and pynput on Windows/X11.
    """

    trigger_detected = pyqtSignal(dict)  # Pass entire snippet

    def __init__(self, snippets, settings=None):
        super().__init__()
        self.snippets = snippets
        self.current_buffer = ""
        self.running = True
        self.keyboard_controller = Controller()
        self.shift_pressed = False
        self.caps_lock = False
        self.pynput_listener = None  # For pynput mode

        # Trigger settings
        settings = settings or {}
        self.case_sensitive = settings.get('case_sensitive', True)
        self.require_delimiter = settings.get('require_delimiter', False)
        self.require_prefix = settings.get('require_prefix', False)
        self.prefix_char = settings.get('prefix_char', '/')

        # Determine which input method to use
        self.use_evdev = IS_LINUX and HAS_EVDEV

        # Key code to character mapping (US layout) - only used for evdev
        if self.use_evdev:
            self.key_map = {
                ecodes.KEY_A: ('a', 'A'), ecodes.KEY_B: ('b', 'B'), ecodes.KEY_C: ('c', 'C'),
                ecodes.KEY_D: ('d', 'D'), ecodes.KEY_E: ('e', 'E'), ecodes.KEY_F: ('f', 'F'),
                ecodes.KEY_G: ('g', 'G'), ecodes.KEY_H: ('h', 'H'), ecodes.KEY_I: ('i', 'I'),
                ecodes.KEY_J: ('j', 'J'), ecodes.KEY_K: ('k', 'K'), ecodes.KEY_L: ('l', 'L'),
                ecodes.KEY_M: ('m', 'M'), ecodes.KEY_N: ('n', 'N'), ecodes.KEY_O: ('o', 'O'),
                ecodes.KEY_P: ('p', 'P'), ecodes.KEY_Q: ('q', 'Q'), ecodes.KEY_R: ('r', 'R'),
                ecodes.KEY_S: ('s', 'S'), ecodes.KEY_T: ('t', 'T'), ecodes.KEY_U: ('u', 'U'),
                ecodes.KEY_V: ('v', 'V'), ecodes.KEY_W: ('w', 'W'), ecodes.KEY_X: ('x', 'X'),
                ecodes.KEY_Y: ('y', 'Y'), ecodes.KEY_Z: ('z', 'Z'),
                ecodes.KEY_1: ('1', '!'), ecodes.KEY_2: ('2', '@'), ecodes.KEY_3: ('3', '#'),
                ecodes.KEY_4: ('4', '$'), ecodes.KEY_5: ('5', '%'), ecodes.KEY_6: ('6', '^'),
                ecodes.KEY_7: ('7', '&'), ecodes.KEY_8: ('8', '*'), ecodes.KEY_9: ('9', '('),
                ecodes.KEY_0: ('0', ')'),
                ecodes.KEY_MINUS: ('-', '_'), ecodes.KEY_EQUAL: ('=', '+'),
                ecodes.KEY_LEFTBRACE: ('[', '{'), ecodes.KEY_RIGHTBRACE: (']', '}'),
                ecodes.KEY_SEMICOLON: (';', ':'), ecodes.KEY_APOSTROPHE: ("'", '"'),
                ecodes.KEY_GRAVE: ('`', '~'), ecodes.KEY_BACKSLASH: ('\\', '|'),
                ecodes.KEY_COMMA: (',', '<'), ecodes.KEY_DOT: ('.', '>'),
                ecodes.KEY_SLASH: ('/', '?'),
                ecodes.KEY_SPACE: (' ', ' '),
                # Numpad keys
                ecodes.KEY_KP0: ('0', '0'), ecodes.KEY_KP1: ('1', '1'), ecodes.KEY_KP2: ('2', '2'),
                ecodes.KEY_KP3: ('3', '3'), ecodes.KEY_KP4: ('4', '4'), ecodes.KEY_KP5: ('5', '5'),
                ecodes.KEY_KP6: ('6', '6'), ecodes.KEY_KP7: ('7', '7'), ecodes.KEY_KP8: ('8', '8'),
                ecodes.KEY_KP9: ('9', '9'), ecodes.KEY_KPDOT: ('.', '.'), ecodes.KEY_KPSLASH: ('/', '/'),
                ecodes.KEY_KPASTERISK: ('*', '*'), ecodes.KEY_KPMINUS: ('-', '-'), ecodes.KEY_KPPLUS: ('+', '+'),
            }

    def find_keyboards(self):
        """Find all keyboard devices (evdev only)"""
        if not self.use_evdev:
            return []
        keyboards = []
        for path in list_devices():
            try:
                device = InputDevice(path)
                capabilities = device.capabilities()
                # Check if device has key events and has letter keys (it's a keyboard)
                if ecodes.EV_KEY in capabilities:
                    keys = capabilities[ecodes.EV_KEY]
                    # Check for common letter keys to identify as keyboard
                    if ecodes.KEY_A in keys and ecodes.KEY_Z in keys:
                        keyboards.append(device)
                        print(f"Found keyboard: {device.name} at {device.path}")
            except Exception as e:
                pass
        return keyboards

    def run(self):
        """Start listening to keyboard input"""
        if self.use_evdev:
            self.run_evdev()
        else:
            self.run_pynput()

    def run_evdev(self):
        """Start listening using evdev (Linux/Wayland)"""
        keyboards = self.find_keyboards()
        if not keyboards:
            print("No keyboards found! Make sure you're in the 'input' group.")
            print("Run: sudo usermod -aG input $USER")
            print("Then log out and back in.")
            # Fall back to pynput
            print("Falling back to pynput...")
            self.use_evdev = False
            self.run_pynput()
            return

        selector = selectors.DefaultSelector()
        for kbd in keyboards:
            selector.register(kbd, selectors.EVENT_READ)

        while self.running:
            for key, mask in selector.select(timeout=0.1):
                device = key.fileobj
                try:
                    for event in device.read():
                        if event.type == ecodes.EV_KEY:
                            self.handle_evdev_event(event)
                except BlockingIOError:
                    pass
                except Exception as e:
                    print(f"Error reading device: {e}")

        selector.close()

    def run_pynput(self):
        """Start listening using pynput (Windows/X11/fallback)"""
        print("Using pynput for keyboard input")

        def on_press(key):
            if not self.running:
                return False
            self.handle_pynput_press(key)

        def on_release(key):
            if not self.running:
                return False
            self.handle_pynput_release(key)

        self.pynput_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.pynput_listener.start()

        # Keep thread alive while running
        while self.running:
            time.sleep(0.1)

        if self.pynput_listener:
            self.pynput_listener.stop()

    def handle_pynput_press(self, key):
        """Handle pynput key press event"""
        try:
            # Get character from key
            if hasattr(key, 'char') and key.char:
                char = key.char
                self.current_buffer += char

                # Keep buffer at reasonable length
                if len(self.current_buffer) > 50:
                    self.current_buffer = self.current_buffer[-50:]

                self.check_triggers()
            elif key == Key.space:
                self.current_buffer = ""
            elif key == Key.enter:
                self.current_buffer = ""
            elif key == Key.backspace:
                if self.current_buffer:
                    self.current_buffer = self.current_buffer[:-1]
        except Exception as e:
            pass

    def handle_pynput_release(self, key):
        """Handle pynput key release event"""
        pass  # We don't need to track releases for basic functionality

    def handle_evdev_event(self, event):
        """Handle an evdev key event (Linux)"""
        # Key states: 0 = up, 1 = down, 2 = hold/repeat

        # Track shift state
        if event.code in (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT):
            self.shift_pressed = event.value != 0
            return

        # Track caps lock
        if event.code == ecodes.KEY_CAPSLOCK and event.value == 1:
            self.caps_lock = not self.caps_lock
            return

        # Only process key down events (not releases or repeats)
        if event.value != 1:
            return

        # Clear buffer on space or enter
        if event.code in (ecodes.KEY_SPACE, ecodes.KEY_ENTER):
            self.current_buffer = ""
            return

        # Handle backspace
        if event.code == ecodes.KEY_BACKSPACE:
            if self.current_buffer:
                self.current_buffer = self.current_buffer[:-1]
            return

        # Convert key code to character
        if event.code in self.key_map:
            lower, upper = self.key_map[event.code]

            # Determine if we should use uppercase
            use_upper = self.shift_pressed
            if lower.isalpha():
                use_upper = self.shift_pressed != self.caps_lock  # XOR for caps lock behavior

            char = upper if use_upper else lower
            self.current_buffer += char

            # Keep buffer at reasonable length
            if len(self.current_buffer) > 50:
                self.current_buffer = self.current_buffer[-50:]

            # Check for matches
            self.check_triggers()

    def check_triggers(self):
        """Check if current buffer matches any trigger based on settings"""
        # Common delimiters that would end a word
        delimiters = ' \t\n.,;:!?()[]{}<>"\'`~@#$%^&*-+=|\\/'

        for snippet in self.snippets:
            trigger = snippet.get('trigger', '')
            if not trigger:
                continue

            # Build the full trigger pattern based on settings
            full_trigger = trigger
            if self.require_prefix:
                full_trigger = self.prefix_char + trigger

            # Check for match (case-sensitive or case-insensitive)
            buffer_to_check = self.current_buffer
            trigger_to_match = full_trigger

            if not self.case_sensitive:
                buffer_to_check = buffer_to_check.lower()
                trigger_to_match = full_trigger.lower()

            if buffer_to_check.endswith(trigger_to_match):
                # Check delimiter requirement
                if self.require_delimiter:
                    # There must be a delimiter before the trigger (or buffer starts with trigger)
                    trigger_start = len(self.current_buffer) - len(full_trigger)
                    if trigger_start > 0:
                        char_before = self.current_buffer[trigger_start - 1]
                        if char_before not in delimiters:
                            continue  # No delimiter before trigger, skip

                print(f"Trigger matched! Buffer: '{self.current_buffer}' | Trigger: '{full_trigger}'")
                self.trigger_detected.emit(snippet)
                self.current_buffer = ""
                break

    def update_snippets(self, snippets):
        """Update the snippets list"""
        self.snippets = snippets

    def stop(self):
        """Stop the listener"""
        self.running = False


class SettingsDialog(QDialog):
    """Dialog for application settings with tabbed interface"""

    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        self.settings = current_settings or {}
        self.parent_window = parent
        self.setWindowTitle("Settings")
        self.setMinimumSize(550, 500)

        # Detect current theme from parent window
        self.is_light_theme = False
        if parent and hasattr(parent, 'current_theme'):
            self.is_light_theme = (parent.current_theme == 'Light')

        self.init_ui()

    def get_dark_stylesheet(self):
        """Return the dark theme stylesheet for settings dialog"""
        return """
            QDialog {
                background-color: #1E1E1E;
            }
            QLabel {
                color: #E0E0E0;
                font-size: 13px;
            }
            QTabWidget::pane {
                border: 1px solid #424242;
                background-color: #1E1E1E;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #2A2A2A;
                color: #888888;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #1E1E1E;
                color: #FF6B00;
                border-bottom: 2px solid #FF6B00;
            }
            QTabBar::tab:hover:!selected {
                background-color: #333333;
            }
            QComboBox, QSpinBox, QLineEdit {
                background-color: #2A2A2A;
                color: #E0E0E0;
                border: 1px solid #424242;
                border-radius: 4px;
                padding: 6px 10px;
                min-width: 120px;
                font-size: 13px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                width: 0;
                height: 0;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #E0E0E0;
            }
            QComboBox QAbstractItemView {
                background-color: #2A2A2A;
                color: #E0E0E0;
                selection-background-color: #FF6B00;
            }
            QCheckBox {
                color: #E0E0E0;
                spacing: 8px;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #424242;
                border-radius: 3px;
                background-color: #2A2A2A;
            }
            QCheckBox::indicator:checked {
                background-color: #FF6B00;
                border-color: #FF6B00;
            }
            QCheckBox::indicator:hover {
                border-color: #FF6B00;
            }
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
            QGroupBox {
                color: #FF6B00;
                font-weight: bold;
                border: 1px solid #424242;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """

    def get_light_stylesheet(self):
        """Return the light theme stylesheet for settings dialog"""
        return """
            QDialog {
                background-color: #F5F5F5;
            }
            QLabel {
                color: #212121;
                font-size: 13px;
            }
            QTabWidget::pane {
                border: 1px solid #E0E0E0;
                background-color: rgba(255, 255, 255, 220);
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: rgba(238, 238, 238, 230);
                color: #616161;
                padding: 8px 16px;
                margin-right: 2px;
                border: 1px solid #E0E0E0;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: rgba(255, 255, 255, 240);
                color: #FF6B00;
                border-bottom: 2px solid #FF6B00;
            }
            QTabBar::tab:hover:!selected {
                background-color: rgba(224, 224, 224, 230);
            }
            QComboBox, QSpinBox, QLineEdit {
                background-color: rgba(255, 255, 255, 230);
                color: #212121;
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                padding: 6px 10px;
                min-width: 120px;
                font-size: 13px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                width: 0;
                height: 0;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #616161;
            }
            QComboBox QAbstractItemView {
                background-color: rgba(255, 255, 255, 250);
                color: #212121;
                selection-background-color: #FFE0B2;
            }
            QCheckBox {
                color: #212121;
                spacing: 8px;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #BDBDBD;
                border-radius: 3px;
                background-color: #FFFFFF;
            }
            QCheckBox::indicator:checked {
                background-color: #FF6B00;
                border-color: #FF6B00;
            }
            QCheckBox::indicator:hover {
                border-color: #FF6B00;
            }
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
            QGroupBox {
                color: #FF6B00;
                font-weight: bold;
                border: 1px solid #E0E0E0;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
                background-color: rgba(255, 255, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """

    def init_ui(self):
        if self.is_light_theme:
            self.setStyleSheet(self.get_light_stylesheet())
        else:
            self.setStyleSheet(self.get_dark_stylesheet())

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title with auto-save indicator
        title_layout = QHBoxLayout()
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #FF6B00;")
        title_layout.addWidget(title)

        self.auto_save_label = QLabel("(changes apply automatically)")
        if self.is_light_theme:
            self.auto_save_label.setStyleSheet("color: #757575; font-size: 12px; font-style: italic;")
        else:
            self.auto_save_label.setStyleSheet("color: #888888; font-size: 12px; font-style: italic;")
        title_layout.addWidget(self.auto_save_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Create tabs
        self.create_appearance_tab()
        self.create_behavior_tab()
        self.create_triggers_tab()
        self.create_datetime_tab()
        self.create_backup_tab()

        # Connect all settings widgets to auto-apply
        self.connect_auto_apply_signals()

        # Single Close button (settings apply automatically)
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def connect_auto_apply_signals(self):
        """Connect all settings widgets to auto-apply changes"""
        # Appearance tab
        self.theme_combo.currentTextChanged.connect(self.apply_settings)
        self.show_background_cb.stateChanged.connect(self.apply_settings)
        self.bg_path_edit.textChanged.connect(self.apply_settings)
        self.bg_light_path_edit.textChanged.connect(self.apply_settings)
        self.bg_opacity_combo.currentTextChanged.connect(self.apply_settings)
        self.font_size_spin.valueChanged.connect(self.apply_settings)

        # Behavior tab
        self.start_minimized_cb.stateChanged.connect(self.apply_settings)
        self.start_on_login_cb.stateChanged.connect(self.apply_settings)
        self.play_sound_cb.stateChanged.connect(self.apply_settings)
        self.show_notification_cb.stateChanged.connect(self.apply_settings)
        self.expansion_delay_spin.valueChanged.connect(self.apply_settings)

        # Triggers tab
        self.case_sensitive_cb.stateChanged.connect(self.apply_settings)
        self.require_delimiter_cb.stateChanged.connect(self.apply_settings)
        self.require_prefix_cb.stateChanged.connect(self.apply_settings)
        self.prefix_char_edit.textChanged.connect(self.apply_settings)
        self.clear_clipboard_cb.stateChanged.connect(self.apply_settings)

        # Date/Time tab
        self.date_format_combo.currentTextChanged.connect(self.apply_settings)
        self.time_format_combo.currentTextChanged.connect(self.apply_settings)
        self.first_day_combo.currentTextChanged.connect(self.apply_settings)

        # Backup tab
        self.auto_backup_cb.stateChanged.connect(self.apply_settings)
        self.backup_path_edit.textChanged.connect(self.apply_settings)

    def apply_settings(self):
        """Apply settings immediately to parent window"""
        if not self.parent_window:
            return

        # Get current settings from widgets
        new_settings = self.get_settings()

        # Update parent's settings
        self.parent_window.settings = new_settings
        self.parent_window.save_settings()

        # Apply visual changes
        self.parent_window.apply_theme()
        self.parent_window.load_background_image()
        self.parent_window.update_background_label()
        self.parent_window.refresh_tree()

        # Update this dialog's theme if theme changed
        new_theme = new_settings.get('theme', 'Dark')
        new_is_light = (new_theme == 'Light')
        if new_is_light != self.is_light_theme:
            self.is_light_theme = new_is_light
            self.update_dialog_theme()

        # Update listener settings
        if hasattr(self.parent_window, 'listener_thread') and self.parent_window.listener_thread:
            self.parent_window.listener_thread.case_sensitive = new_settings.get('case_sensitive', True)
            self.parent_window.listener_thread.require_delimiter = new_settings.get('require_delimiter', False)
            self.parent_window.listener_thread.require_prefix = new_settings.get('require_prefix', False)
            self.parent_window.listener_thread.prefix_char = new_settings.get('prefix_char', '/')

    def update_dialog_theme(self):
        """Update the dialog's stylesheet based on current theme"""
        if self.is_light_theme:
            self.setStyleSheet(self.get_light_stylesheet())
            self.auto_save_label.setStyleSheet("color: #757575; font-size: 12px; font-style: italic;")
        else:
            self.setStyleSheet(self.get_dark_stylesheet())
            self.auto_save_label.setStyleSheet("color: #888888; font-size: 12px; font-style: italic;")

    def create_appearance_tab(self):
        """Create the Appearance settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # Theme section
        theme_group = QGroupBox("Theme")
        theme_layout = QHBoxLayout(theme_group)
        theme_layout.addWidget(QLabel("Color theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(['Dark', 'Light', 'Auto (System)'])
        current_theme = self.settings.get('theme', 'Dark')
        index = self.theme_combo.findText(current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        layout.addWidget(theme_group)

        # Background Image section
        bg_group = QGroupBox("Background")
        bg_layout = QVBoxLayout(bg_group)

        self.show_background_cb = QCheckBox("Show background image")
        self.show_background_cb.setChecked(self.settings.get('show_background', True))
        bg_layout.addWidget(self.show_background_cb)

        bg_path_layout = QHBoxLayout()
        bg_path_layout.addWidget(QLabel("Custom image:"))
        self.bg_path_edit = QLineEdit()
        self.bg_path_edit.setPlaceholderText("Default (background.png)")
        self.bg_path_edit.setText(self.settings.get('custom_background', ''))
        bg_path_layout.addWidget(self.bg_path_edit)

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_background)
        browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A90D9;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #5AA0E9;
            }
        """)
        bg_path_layout.addWidget(browse_btn)
        bg_layout.addLayout(bg_path_layout)

        # Light mode background
        bg_light_layout = QHBoxLayout()
        bg_light_layout.addWidget(QLabel("Light mode image:"))
        self.bg_light_path_edit = QLineEdit()
        self.bg_light_path_edit.setPlaceholderText("Default (background_light.png)")
        self.bg_light_path_edit.setText(self.settings.get('custom_background_light', ''))
        bg_light_layout.addWidget(self.bg_light_path_edit)

        browse_light_btn = QPushButton("Browse")
        browse_light_btn.clicked.connect(self.browse_background_light)
        browse_light_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A90D9;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #5AA0E9;
            }
        """)
        bg_light_layout.addWidget(browse_light_btn)
        bg_layout.addLayout(bg_light_layout)

        # Background opacity
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("Opacity:"))
        self.bg_opacity_combo = QComboBox()
        self.bg_opacity_combo.addItems(['0%', '25%', '50%', '75%', '100%'])
        current_opacity = self.settings.get('background_opacity', '50%')
        index = self.bg_opacity_combo.findText(current_opacity)
        if index >= 0:
            self.bg_opacity_combo.setCurrentIndex(index)
        opacity_layout.addWidget(self.bg_opacity_combo)
        opacity_layout.addStretch()
        bg_layout.addLayout(opacity_layout)

        layout.addWidget(bg_group)

        # Font section
        font_group = QGroupBox("Editor Font")
        font_layout = QHBoxLayout(font_group)

        font_layout.addWidget(QLabel("Size:"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(10, 24)
        self.font_size_spin.setValue(self.settings.get('font_size', 14))
        font_layout.addWidget(self.font_size_spin)
        font_layout.addStretch()

        layout.addWidget(font_group)

        layout.addStretch()
        self.tabs.addTab(tab, "Appearance")

    def create_behavior_tab(self):
        """Create the Behavior settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # Startup section
        startup_group = QGroupBox("Startup")
        startup_layout = QVBoxLayout(startup_group)

        self.start_minimized_cb = QCheckBox("Start minimized to system tray")
        self.start_minimized_cb.setChecked(self.settings.get('start_minimized', True))
        startup_layout.addWidget(self.start_minimized_cb)

        self.start_on_login_cb = QCheckBox("Start on system login")
        self.start_on_login_cb.setChecked(self.settings.get('start_on_login', False))
        startup_layout.addWidget(self.start_on_login_cb)

        layout.addWidget(startup_group)

        # Notifications section
        notif_group = QGroupBox("Notifications")
        notif_layout = QVBoxLayout(notif_group)

        self.play_sound_cb = QCheckBox("Play sound on expansion")
        self.play_sound_cb.setChecked(self.settings.get('play_sound', False))
        notif_layout.addWidget(self.play_sound_cb)

        self.show_notification_cb = QCheckBox("Show notification on expansion")
        self.show_notification_cb.setChecked(self.settings.get('show_notification', False))
        notif_layout.addWidget(self.show_notification_cb)

        layout.addWidget(notif_group)

        # Expansion section
        expansion_group = QGroupBox("Expansion")
        expansion_layout = QVBoxLayout(expansion_group)

        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("Expansion delay (ms):"))
        self.expansion_delay_spin = QSpinBox()
        self.expansion_delay_spin.setRange(0, 500)
        self.expansion_delay_spin.setSingleStep(10)
        self.expansion_delay_spin.setValue(self.settings.get('expansion_delay', 50))
        delay_layout.addWidget(self.expansion_delay_spin)
        delay_layout.addStretch()
        expansion_layout.addLayout(delay_layout)

        layout.addWidget(expansion_group)

        layout.addStretch()
        self.tabs.addTab(tab, "Behavior")

    def create_triggers_tab(self):
        """Create the Triggers settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # Matching section
        match_group = QGroupBox("Trigger Matching")
        match_layout = QVBoxLayout(match_group)

        self.case_sensitive_cb = QCheckBox("Case sensitive triggers")
        self.case_sensitive_cb.setChecked(self.settings.get('case_sensitive', True))
        match_layout.addWidget(self.case_sensitive_cb)

        self.require_delimiter_cb = QCheckBox("Require space/punctuation after trigger")
        self.require_delimiter_cb.setChecked(self.settings.get('require_delimiter', False))
        match_layout.addWidget(self.require_delimiter_cb)

        layout.addWidget(match_group)

        # Prefix section
        prefix_group = QGroupBox("Trigger Prefix")
        prefix_layout = QVBoxLayout(prefix_group)

        self.require_prefix_cb = QCheckBox("Only expand triggers starting with specific character")
        self.require_prefix_cb.setChecked(self.settings.get('require_prefix', False))
        prefix_layout.addWidget(self.require_prefix_cb)

        prefix_char_layout = QHBoxLayout()
        prefix_char_layout.addWidget(QLabel("Prefix character:"))
        self.prefix_char_edit = QLineEdit()
        self.prefix_char_edit.setMaxLength(1)
        self.prefix_char_edit.setMaximumWidth(50)
        self.prefix_char_edit.setText(self.settings.get('prefix_char', '/'))
        prefix_char_layout.addWidget(self.prefix_char_edit)
        prefix_char_layout.addStretch()
        prefix_layout.addLayout(prefix_char_layout)

        layout.addWidget(prefix_group)

        # Clipboard section
        clip_group = QGroupBox("Clipboard")
        clip_layout = QVBoxLayout(clip_group)

        self.clear_clipboard_cb = QCheckBox("Clear clipboard after paste")
        self.clear_clipboard_cb.setChecked(self.settings.get('clear_clipboard', False))
        clip_layout.addWidget(self.clear_clipboard_cb)

        layout.addWidget(clip_group)

        layout.addStretch()
        self.tabs.addTab(tab, "Triggers")

    def create_datetime_tab(self):
        """Create the Date/Time settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # Date format section
        date_group = QGroupBox("Date Format")
        date_layout = QVBoxLayout(date_group)

        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format:"))
        self.date_format_combo = QComboBox()
        date_formats = ['MM/DD/YYYY', 'DD/MM/YYYY', 'YYYY-MM-DD', 'MM-DD-YYYY', 'DD-MM-YYYY']
        self.date_format_combo.addItems(date_formats)
        current_format = self.settings.get('date_format', 'MM/DD/YYYY')
        index = self.date_format_combo.findText(current_format)
        if index >= 0:
            self.date_format_combo.setCurrentIndex(index)
        format_layout.addWidget(self.date_format_combo)
        format_layout.addStretch()
        date_layout.addLayout(format_layout)

        self.date_preview_label = QLabel()
        self.date_preview_label.setStyleSheet("color: #888888; font-style: italic;")
        self.update_date_preview()
        self.date_format_combo.currentTextChanged.connect(self.update_date_preview)
        date_layout.addWidget(self.date_preview_label)

        layout.addWidget(date_group)

        # Time format section
        time_group = QGroupBox("Time Format")
        time_layout = QVBoxLayout(time_group)

        time_format_layout = QHBoxLayout()
        time_format_layout.addWidget(QLabel("Format:"))
        self.time_format_combo = QComboBox()
        self.time_format_combo.addItems(['12-hour (3:30 PM)', '24-hour (15:30)'])
        current_time = self.settings.get('time_format', '12-hour (3:30 PM)')
        index = self.time_format_combo.findText(current_time)
        if index >= 0:
            self.time_format_combo.setCurrentIndex(index)
        time_format_layout.addWidget(self.time_format_combo)
        time_format_layout.addStretch()
        time_layout.addLayout(time_format_layout)

        layout.addWidget(time_group)

        # Calendar section
        cal_group = QGroupBox("Calendar")
        cal_layout = QVBoxLayout(cal_group)

        week_layout = QHBoxLayout()
        week_layout.addWidget(QLabel("First day of week:"))
        self.first_day_combo = QComboBox()
        self.first_day_combo.addItems(['Sunday', 'Monday'])
        current_day = self.settings.get('first_day_of_week', 'Sunday')
        index = self.first_day_combo.findText(current_day)
        if index >= 0:
            self.first_day_combo.setCurrentIndex(index)
        week_layout.addWidget(self.first_day_combo)
        week_layout.addStretch()
        cal_layout.addLayout(week_layout)

        layout.addWidget(cal_group)

        layout.addStretch()
        self.tabs.addTab(tab, "Date/Time")

    def create_backup_tab(self):
        """Create the Backup settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # Auto-backup section
        backup_group = QGroupBox("Auto-Backup")
        backup_layout = QVBoxLayout(backup_group)

        self.auto_backup_cb = QCheckBox("Enable automatic backups")
        self.auto_backup_cb.setChecked(self.settings.get('auto_backup', False))
        backup_layout.addWidget(self.auto_backup_cb)

        backup_path_layout = QHBoxLayout()
        backup_path_layout.addWidget(QLabel("Backup location:"))
        self.backup_path_edit = QLineEdit()
        self.backup_path_edit.setPlaceholderText("~/.config/snipforge/backups/")
        self.backup_path_edit.setText(self.settings.get('backup_path', ''))
        backup_path_layout.addWidget(self.backup_path_edit)

        backup_browse_btn = QPushButton("Browse")
        backup_browse_btn.clicked.connect(self.browse_backup_location)
        backup_browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A90D9;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #5AA0E9;
            }
        """)
        backup_path_layout.addWidget(backup_browse_btn)
        backup_layout.addLayout(backup_path_layout)

        layout.addWidget(backup_group)

        # Export/Import section
        export_group = QGroupBox("Export / Import")
        export_layout = QVBoxLayout(export_group)

        export_btn_layout = QHBoxLayout()

        export_btn = QPushButton("Export Snippets")
        export_btn.clicked.connect(self.export_snippets)
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A90D9;
            }
            QPushButton:hover {
                background-color: #5AA0E9;
            }
        """)
        export_btn_layout.addWidget(export_btn)

        import_btn = QPushButton("Import Snippets")
        import_btn.clicked.connect(self.import_snippets)
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A90D9;
            }
            QPushButton:hover {
                background-color: #5AA0E9;
            }
        """)
        export_btn_layout.addWidget(import_btn)

        export_btn_layout.addStretch()
        export_layout.addLayout(export_btn_layout)

        layout.addWidget(export_group)

        layout.addStretch()
        self.tabs.addTab(tab, "Backup")

    def browse_background(self):
        """Browse for a custom background image"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Background Image", str(Path.home()),
            "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if file_path:
            self.bg_path_edit.setText(file_path)

    def browse_background_light(self):
        """Browse for a custom light mode background image"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Light Mode Background Image", str(Path.home()),
            "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if file_path:
            self.bg_light_path_edit.setText(file_path)

    def browse_backup_location(self):
        """Browse for backup location"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Backup Location", str(Path.home())
        )
        if dir_path:
            self.backup_path_edit.setText(dir_path)

    def export_snippets(self):
        """Export snippets to a file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Snippets", str(Path.home() / "snippets_export.json"),
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path and self.parent_window:
            try:
                with open(file_path, 'w') as f:
                    json.dump(self.parent_window.snippets, f, indent=2)
                QMessageBox.information(self, "Export Complete",
                                       f"Exported {len(self.parent_window.snippets)} snippets to:\n{file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Export Failed", f"Error exporting snippets:\n{e}")

    def import_snippets(self):
        """Import snippets from a file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Snippets", str(Path.home()),
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path and self.parent_window:
            try:
                with open(file_path, 'r') as f:
                    imported = json.load(f)
                if isinstance(imported, list):
                    reply = QMessageBox.question(
                        self, "Import Snippets",
                        f"Import {len(imported)} snippets?\n\nThis will add to your existing snippets.",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        self.parent_window.snippets.extend(imported)
                        self.parent_window.save_snippets()
                        self.parent_window.refresh_tree()
                        QMessageBox.information(self, "Import Complete",
                                               f"Imported {len(imported)} snippets.")
                else:
                    QMessageBox.warning(self, "Import Failed", "Invalid snippet file format.")
            except Exception as e:
                QMessageBox.warning(self, "Import Failed", f"Error importing snippets:\n{e}")

    def update_date_preview(self):
        """Update the date format preview"""
        format_name = self.date_format_combo.currentText()
        formats = {
            'MM/DD/YYYY': '%m/%d/%Y',
            'DD/MM/YYYY': '%d/%m/%Y',
            'YYYY-MM-DD': '%Y-%m-%d',
            'MM-DD-YYYY': '%m-%d-%Y',
            'DD-MM-YYYY': '%d-%m-%Y',
        }
        fmt = formats.get(format_name, '%m/%d/%Y')
        preview = datetime.now().strftime(fmt)
        self.date_preview_label.setText(f"Preview: {preview}")

    def get_settings(self):
        """Return all updated settings"""
        return {
            # Appearance
            'theme': self.theme_combo.currentText(),
            'show_background': self.show_background_cb.isChecked(),
            'custom_background': self.bg_path_edit.text(),
            'custom_background_light': self.bg_light_path_edit.text(),
            'background_opacity': self.bg_opacity_combo.currentText(),
            'font_size': self.font_size_spin.value(),
            # Behavior
            'start_minimized': self.start_minimized_cb.isChecked(),
            'start_on_login': self.start_on_login_cb.isChecked(),
            'play_sound': self.play_sound_cb.isChecked(),
            'show_notification': self.show_notification_cb.isChecked(),
            'expansion_delay': self.expansion_delay_spin.value(),
            # Triggers
            'case_sensitive': self.case_sensitive_cb.isChecked(),
            'require_delimiter': self.require_delimiter_cb.isChecked(),
            'require_prefix': self.require_prefix_cb.isChecked(),
            'prefix_char': self.prefix_char_edit.text(),
            'clear_clipboard': self.clear_clipboard_cb.isChecked(),
            # Date/Time
            'date_format': self.date_format_combo.currentText(),
            'time_format': self.time_format_combo.currentText(),
            'first_day_of_week': self.first_day_combo.currentText(),
            # Backup
            'auto_backup': self.auto_backup_cb.isChecked(),
            'backup_path': self.backup_path_edit.text(),
        }


class MainWindow(QMainWindow):
    """Main application window"""

    # Date format options
    DATE_FORMATS = {
        'MM/DD/YYYY': '%m/%d/%Y',
        'DD/MM/YYYY': '%d/%m/%Y',
        'YYYY-MM-DD': '%Y-%m-%d',
        'MM-DD-YYYY': '%m-%d-%Y',
        'DD-MM-YYYY': '%d-%m-%Y',
    }

    TIME_FORMATS = {
        '12-hour (3:30 PM)': '%I:%M %p',
        '24-hour (15:30)': '%H:%M',
        '12-hour with seconds (3:30:45 PM)': '%I:%M:%S %p',
        '24-hour with seconds (15:30:45)': '%H:%M:%S',
    }

    def get_dark_theme(self):
        """Return the dark theme stylesheet"""
        return """
            QMainWindow, QDialog {
                background-color: #000000;
            }
            QWidget {
                font-family: 'Segoe UI', 'Roboto', 'Noto Sans', sans-serif;
                font-size: 14px;
                color: #E0E0E0;
            }
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: 500;
                min-height: 36px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
            QPushButton:disabled {
                background-color: #424242;
                color: #757575;
            }
            QPushButton#backBtn {
                background-color: transparent;
                color: #9E9E9E;
                border: 1px solid #616161;
                border-radius: 4px;
                font-size: 18px;
                font-weight: normal;
                padding: 0px;
                margin: 0px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }
            QPushButton#backBtn:hover {
                background-color: #3D3D3D;
                color: #FFFFFF;
                border: 1px solid #9E9E9E;
            }
            QPushButton#backBtn:pressed {
                background-color: #4A4A4A;
                color: #FFFFFF;
                border: 1px solid #9E9E9E;
            }
            QTableWidget {
                background-color: rgba(0, 0, 0, 100);
                border: 1px solid #333333;
                border-radius: 4px;
                gridline-color: #2A2A2A;
                selection-background-color: #3D2814;
                selection-color: #FFFFFF;
                color: #E0E0E0;
            }
            QTableWidget::item {
                padding: 12px 8px;
                border-bottom: 1px solid #2A2A2A;
                color: #E0E0E0;
                background-color: transparent;
            }
            QTableWidget::item:selected {
                background-color: #3D2814;
                color: #FFFFFF;
            }
            QHeaderView::section {
                background-color: rgba(0, 0, 0, 120);
                color: #E0E0E0;
                font-weight: 600;
                padding: 12px 8px;
                border: none;
                border-bottom: 2px solid #FF6B00;
            }
            QLineEdit, QTextEdit {
                background-color: rgba(30, 30, 30, 215);
                border: 1px solid #424242;
                border-radius: 4px;
                padding: 8px;
                color: #E0E0E0;
                selection-background-color: #3D2814;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 2px solid #FF6B00;
                padding: 7px;
            }
            QLabel {
                color: #E0E0E0;
            }
            QMenu {
                background-color: #1E1E1E;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 0px;
            }
            QMenu::item {
                padding: 8px 24px;
                color: #E0E0E0;
            }
            QMenu::item:selected {
                background-color: #333333;
            }
            QMessageBox {
                background-color: #121212;
            }
            QMessageBox QLabel {
                color: #E0E0E0;
            }
            QInputDialog {
                background-color: #121212;
            }
            QComboBox {
                background-color: rgba(30, 30, 30, 215);
                border: 1px solid #424242;
                border-radius: 4px;
                padding: 8px;
                min-height: 20px;
                color: #E0E0E0;
            }
            QComboBox:focus {
                border: 2px solid #FF6B00;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #1E1E1E;
                color: #E0E0E0;
                selection-background-color: #3D2814;
            }
            QScrollBar:vertical {
                background-color: #1E1E1E;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #424242;
                border-radius: 6px;
                min-height: 40px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #FF6B00;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QTreeWidget {
                background-color: rgba(0, 0, 0, 100);
                border: 1px solid #333333;
                border-radius: 4px;
                selection-background-color: #3D2814;
                selection-color: #FFFFFF;
                color: #E0E0E0;
                outline: none;
            }
            QTreeWidget::item {
                padding: 8px 4px;
                border-bottom: 1px solid #2A2A2A;
                color: #E0E0E0;
                background-color: transparent;
            }
            QTreeWidget::item:selected {
                background-color: #3D2814;
                color: #FFFFFF;
            }
            QTreeWidget::branch {
                background-color: transparent;
            }
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {
                image: url(none);
                border-image: none;
            }
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {
                image: url(none);
                border-image: none;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #424242;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
                color: #E0E0E0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QCheckBox {
                color: #E0E0E0;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QSpinBox {
                background-color: rgba(30, 30, 30, 215);
                border: 1px solid #424242;
                border-radius: 4px;
                padding: 4px;
                padding-right: 20px;
                color: #E0E0E0;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #3D3D3D;
                border: 1px solid #555555;
                width: 18px;
            }
            QSpinBox::up-button {
                border-top-right-radius: 3px;
                subcontrol-origin: border;
                subcontrol-position: top right;
            }
            QSpinBox::down-button {
                border-bottom-right-radius: 3px;
                subcontrol-origin: border;
                subcontrol-position: bottom right;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #4A4A4A;
                border-color: #757575;
            }
            QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
                background-color: #555555;
            }
            QTabWidget::pane {
                border: 1px solid #424242;
                border-radius: 4px;
                background-color: #1E1E1E;
            }
            QTabBar::tab {
                background-color: #2A2A2A;
                color: #E0E0E0;
                padding: 8px 16px;
                border: 1px solid #424242;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #1E1E1E;
                border-bottom: 2px solid #FF6B00;
            }
            QTabBar::tab:hover:!selected {
                background-color: #333333;
            }
            QToolTip {
                background-color: #424242;
                color: #FFFFFF;
                border: 1px solid #616161;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """

    def get_light_theme(self):
        """Return the light theme stylesheet with transparency"""
        return """
            QMainWindow, QDialog {
                background-color: rgba(245, 245, 245, 230);
            }
            QWidget {
                font-family: 'Segoe UI', 'Roboto', 'Noto Sans', sans-serif;
                font-size: 14px;
                color: #212121;
            }
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: 500;
                min-height: 36px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
                color: #757575;
            }
            QPushButton#backBtn {
                background-color: transparent;
                color: #757575;
                border: 1px solid #9E9E9E;
                border-radius: 4px;
                font-size: 18px;
                font-weight: normal;
                padding: 0px;
                margin: 0px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }
            QPushButton#backBtn:hover {
                background-color: #D5D5D5;
                color: #333333;
                border: 1px solid #757575;
            }
            QPushButton#backBtn:pressed {
                background-color: #C0C0C0;
                color: #333333;
                border: 1px solid #757575;
            }
            QTableWidget {
                background-color: rgba(215, 215, 215, 235);
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                gridline-color: #D0D0D0;
                selection-background-color: #E67E00;
                selection-color: #FFFFFF;
                color: #212121;
            }
            QTableWidget::item {
                padding: 12px 8px;
                border-bottom: 1px solid #D0D0D0;
                color: #212121;
                background-color: transparent;
            }
            QTableWidget::item:selected {
                background-color: #FFE0B2;
                color: #212121;
            }
            QHeaderView::section {
                background-color: rgba(220, 220, 220, 230);
                color: #212121;
                font-weight: 600;
                padding: 12px 8px;
                border: none;
                border-bottom: 2px solid #FF6B00;
            }
            QLineEdit, QTextEdit {
                background-color: rgba(220, 220, 220, 245);
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                padding: 8px;
                color: #212121;
                selection-background-color: #E67E00;
                selection-color: #FFFFFF;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 2px solid #FF6B00;
                padding: 7px;
            }
            QLabel {
                color: #212121;
            }
            QMenu {
                background-color: rgba(255, 255, 255, 245);
                border: 1px solid #E0E0E0;
                border-radius: 4px;
                padding: 4px 0px;
            }
            QMenu::item {
                padding: 8px 24px;
                color: #212121;
            }
            QMenu::item:selected {
                background-color: #EEEEEE;
            }
            QMessageBox {
                background-color: rgba(255, 255, 255, 240);
            }
            QMessageBox QLabel {
                color: #212121;
            }
            QInputDialog {
                background-color: rgba(255, 255, 255, 240);
            }
            QComboBox {
                background-color: rgba(220, 220, 220, 245);
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                padding: 8px;
                min-height: 20px;
                color: #212121;
            }
            QComboBox:focus {
                border: 2px solid #FF6B00;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: rgba(240, 240, 240, 250);
                color: #212121;
                selection-background-color: #E67E00;
                selection-color: #FFFFFF;
            }
            QScrollBar:vertical {
                background-color: rgba(245, 245, 245, 200);
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #BDBDBD;
                border-radius: 6px;
                min-height: 40px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #FF6B00;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QTreeWidget {
                background-color: rgba(215, 215, 215, 235);
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                selection-background-color: #E67E00;
                selection-color: #FFFFFF;
                color: #212121;
                outline: none;
            }
            QTreeWidget::item {
                padding: 8px 4px;
                border-bottom: 1px solid #D0D0D0;
                color: #212121;
                background-color: transparent;
            }
            QTreeWidget::item:selected {
                background-color: #FFE0B2;
                color: #212121;
            }
            QTreeWidget::branch {
                background-color: transparent;
            }
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {
                image: url(none);
                border-image: none;
            }
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {
                image: url(none);
                border-image: none;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #E0E0E0;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
                color: #212121;
                background-color: rgba(255, 255, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QCheckBox {
                color: #212121;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QSpinBox {
                background-color: rgba(255, 255, 255, 230);
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                padding: 4px;
                padding-right: 20px;
                color: #212121;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #E0E0E0;
                border: 1px solid #9E9E9E;
                width: 18px;
            }
            QSpinBox::up-button {
                border-top-right-radius: 3px;
                subcontrol-origin: border;
                subcontrol-position: top right;
            }
            QSpinBox::down-button {
                border-bottom-right-radius: 3px;
                subcontrol-origin: border;
                subcontrol-position: bottom right;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #D0D0D0;
                border-color: #757575;
            }
            QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
                background-color: #BDBDBD;
            }
            QTabWidget::pane {
                border: 1px solid #E0E0E0;
                border-radius: 4px;
                background-color: rgba(255, 255, 255, 220);
            }
            QTabBar::tab {
                background-color: rgba(238, 238, 238, 230);
                color: #212121;
                padding: 8px 16px;
                border: 1px solid #E0E0E0;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: rgba(255, 255, 255, 240);
                border-bottom: 2px solid #FF6B00;
            }
            QTabBar::tab:hover:!selected {
                background-color: rgba(224, 224, 224, 230);
            }
            QToolTip {
                background-color: #333333;
                color: #FFFFFF;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """

    def detect_system_theme(self):
        """Detect system theme (dark or light)"""
        # Try to detect from environment or system settings
        # Check KDE/Plasma color scheme
        try:
            import subprocess
            result = subprocess.run(
                ['kreadconfig5', '--group', 'General', '--key', 'ColorScheme'],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                scheme = result.stdout.strip().lower()
                if 'dark' in scheme or 'breeze-dark' in scheme:
                    return 'Dark'
                return 'Light'
        except:
            pass

        # Check GTK theme
        try:
            import subprocess
            result = subprocess.run(
                ['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                if 'dark' in result.stdout.lower():
                    return 'Dark'
                return 'Light'
        except:
            pass

        # Default to dark if unable to detect
        return 'Dark'

    def apply_theme(self):
        """Apply the current theme based on settings"""
        theme = self.settings.get('theme', 'Dark')

        if theme == 'Auto (System)':
            theme = self.detect_system_theme()

        if theme == 'Light':
            self.setStyleSheet(self.get_light_theme())
        else:
            self.setStyleSheet(self.get_dark_theme())

        # Set tooltip palette for proper colors (works with native tooltips)
        from PyQt5.QtGui import QPalette, QColor
        palette = QApplication.instance().palette()
        palette.setColor(QPalette.ToolTipBase, QColor('#333333'))
        palette.setColor(QPalette.ToolTipText, QColor('#FFFFFF'))
        QApplication.instance().setPalette(palette)

        # Update folder colors for the tree based on theme
        self.current_theme = theme

        # Update editor widget theme if it exists
        if hasattr(self, 'editor_widget'):
            self.editor_widget.update_theme(theme == 'Light')

    def __init__(self):
        super().__init__()
        # Platform-aware config directory
        config_dir = get_config_dir()
        self.config_file = config_dir / 'snippets.json'
        self.folders_file = config_dir / 'folders.json'
        self.settings_file = config_dir / 'settings.json'
        self.emoji_favorites_file = config_dir / 'emoji_favorites.json'
        self.custom_emojis_file = config_dir / 'custom_emojis.json'
        self.custom_emojis_dir = config_dir / 'custom_emojis'
        config_dir.mkdir(parents=True, exist_ok=True)
        self.custom_emojis_dir.mkdir(parents=True, exist_ok=True)
        self.snippets = self.load_snippets()
        self.custom_folders = self.load_folders()
        self.settings = self.load_settings()
        self.keyboard_controller = Controller()
        self.form_inputs = {}

        # Emoji database cache (built once on first use)
        self._emoji_database_cache = None
        self._emoji_search_index_cache = None
        self._emoji_categories_cache = None
        
        # Setup shared memory for single instance communication
        self.shared_memory = QSharedMemory("SnipForgeInstance")
        
        # Load background image based on settings
        self.background_pixmap = None
        self.load_background_image()

        self.init_ui()
        self.init_system_tray()
        self.start_listener()

        # Timer to check for show requests
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_show_request)
        self.check_timer.start(500)  # Check every 500ms

        # Show tutorial on first run
        if not self.settings.get('tutorial_completed', False):
            # Use a timer to show tutorial after window is fully initialized
            QTimer.singleShot(500, self.show_tutorial)

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("SnipForge")
        self.setGeometry(100, 100, 900, 600)
        self.setMinimumSize(600, 400)  # Allow window to be resized smaller

        # Set window icon
        app_icon_path = get_config_dir() / 'app_icon.ico'
        if app_icon_path.exists():
            self.setWindowIcon(QIcon(str(app_icon_path)))

        # Apply theme based on settings
        self.apply_theme()

        # Central widget with stacked layout for switching views
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        # Background watermark label (not in layout, positioned manually)
        self.bg_label = QLabel(central_widget)
        self.bg_label.setAlignment(Qt.AlignCenter)
        self.bg_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.bg_label.setStyleSheet("background: transparent;")
        self.bg_opacity = 0.50

        # Main layout for central widget
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)

        # Stacked widget for switching between list and editor views
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet("background: transparent;")
        central_layout.addWidget(self.stacked_widget)

        # === List View (index 0) ===
        list_view = QWidget()
        list_view.setStyleSheet("background: transparent;")
        list_layout = QVBoxLayout(list_view)
        list_layout.setSpacing(16)
        list_layout.setContentsMargins(24, 24, 24, 24)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        add_btn = QPushButton("  Add Snippet")
        add_btn.clicked.connect(self.add_snippet)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF6B00;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
        """)

        edit_btn = QPushButton("  Edit")
        edit_btn.clicked.connect(self.edit_snippet)
        edit_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A90D9;
            }
            QPushButton:hover {
                background-color: #5BA3E0;
            }
            QPushButton:pressed {
                background-color: #3A7BC0;
            }
        """)

        delete_btn = QPushButton("  Delete")
        delete_btn.clicked.connect(self.delete_snippet)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #8B2500;
            }
            QPushButton:hover {
                background-color: #A52A00;
            }
            QPushButton:pressed {
                background-color: #6B1C00;
            }
        """)

        new_folder_btn = QPushButton("  New Folder")
        new_folder_btn.clicked.connect(self.add_folder)
        new_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #4A90D9;
                border: 2px solid #4A90D9;
            }
            QPushButton:hover {
                background-color: #1A2A3A;
            }
            QPushButton:pressed {
                background-color: #0A1A2A;
            }
        """)

        toolbar.addWidget(add_btn)
        toolbar.addWidget(edit_btn)
        toolbar.addWidget(delete_btn)
        toolbar.addWidget(new_folder_btn)

        toolbar.addStretch()

        # Settings button with gear icon (moved to right side)
        settings_btn = QPushButton("⚙")
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self.show_settings)
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: 1px solid #424242;
                font-size: 18px;
                padding: 6px 12px;
                min-width: 36px;
            }
            QPushButton:hover {
                background-color: #252525;
                border-color: #555555;
                color: #E0E0E0;
            }
            QPushButton:pressed {
                background-color: #1E1E1E;
            }
        """)
        toolbar.addWidget(settings_btn)

        self.status_indicator = QLabel()
        self.update_status_indicator(True)
        toolbar.addWidget(self.status_indicator)

        list_layout.addLayout(toolbar)

        # Tree widget for folder organization
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Trigger", "Description", "Type"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setStyleSheet("""
            QHeaderView::section {
                background-color: rgba(0, 0, 0, 120);
                color: #E0E0E0;
                font-weight: 600;
                padding: 12px 8px;
                border: none;
                border-bottom: 2px solid #FF6B00;
            }
        """)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(20)
        self.tree.clicked.connect(self.on_tree_click)
        self.tree.doubleClicked.connect(self.on_tree_double_click)
        self.tree.itemExpanded.connect(self.on_folder_expanded)
        self.tree.itemCollapsed.connect(self.on_folder_collapsed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.tree.viewport().setStyleSheet("background: transparent;")
        list_layout.addWidget(self.tree)

        # Info card - Dark forge style
        info_label = QLabel("Tip: The app runs in the background. Close this window to minimize to system tray.")
        info_label.setStyleSheet("""
            QLabel {
                padding: 16px;
                background-color: #1A1A1A;
                color: #B0B0B0;
                border-radius: 4px;
                border-left: 4px solid #FF6B00;
            }
        """)
        list_layout.addWidget(info_label)

        self.stacked_widget.addWidget(list_view)  # Index 0

        # === Editor View (index 1) ===
        self.editor_widget = SnippetEditorWidget()
        self.editor_widget.save_requested.connect(self.on_editor_save)
        self.editor_widget.cancel_requested.connect(self.on_editor_cancel)
        self.editor_widget.set_date_format_getter(self.get_date_format)
        self.editor_widget.set_time_format_getter(self.get_time_format)
        # Set initial theme based on current_theme
        if hasattr(self, 'current_theme'):
            self.editor_widget.update_theme(self.current_theme == 'Light')
        self.stacked_widget.addWidget(self.editor_widget)  # Index 1

        self.refresh_tree()
        self.update_background_label()
        self.bg_label.lower()  # Send to back after all widgets are added

    def init_system_tray(self):
        """Initialize system tray icon"""
        # Load tray icon from file
        tray_icon_path = get_config_dir() / 'tray_icon.ico'
        if tray_icon_path.exists():
            icon = QIcon(str(tray_icon_path))
        else:
            # Fallback: Create a simple icon
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(255, 107, 0))
            painter.setPen(QColor(255, 107, 0))
            painter.drawEllipse(8, 8, 48, 48)
            painter.end()
            icon = QIcon(pixmap)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("SnipForge")
        
        # Create tray menu
        tray_menu = QMenu()
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_application)
        
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()
    
    def tray_icon_activated(self, reason):
        """Handle tray icon clicks"""
        if reason == QSystemTrayIcon.Trigger or reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.activateWindow()
            self.raise_()
    
    def closeEvent(self, event):
        """Handle window close - minimize to tray instead"""
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "SnipForge",
            "Application minimized to tray. Your snippets are still active!",
            QSystemTrayIcon.Information,
            2000
        )

    def resizeEvent(self, event):
        """Handle window resize - update background label"""
        super().resizeEvent(event)
        self.update_background_label()

    def load_background_image(self):
        """Load background image based on settings and current theme"""
        self.background_pixmap = None

        if not self.settings.get('show_background', True):
            return

        # Determine current theme
        theme = self.settings.get('theme', 'Dark')
        if theme == 'Auto (System)':
            theme = self.detect_system_theme()
        is_light = (theme == 'Light')

        # Check for custom background first
        custom_bg = self.settings.get('custom_background', '')
        custom_bg_light = self.settings.get('custom_background_light', '')

        if is_light and custom_bg_light and Path(custom_bg_light).exists():
            # Use custom light mode background
            self.background_pixmap = QPixmap(custom_bg_light)
        elif custom_bg and Path(custom_bg).exists():
            # Use custom background (works for both modes if no light-specific one)
            self.background_pixmap = QPixmap(custom_bg)
        else:
            # Use default background based on theme
            config_dir = get_config_dir()
            if is_light:
                # Try light mode background first
                bg_path_light = config_dir / 'background_light.png'
                if bg_path_light.exists():
                    self.background_pixmap = QPixmap(str(bg_path_light))
                else:
                    # Fall back to regular background
                    bg_path = config_dir / 'background.png'
                    if bg_path.exists():
                        self.background_pixmap = QPixmap(str(bg_path))
            else:
                # Dark mode - use default background
                bg_path = config_dir / 'background.png'
                if bg_path.exists():
                    self.background_pixmap = QPixmap(str(bg_path))

        # Set opacity from settings
        opacity_str = self.settings.get('background_opacity', '50%')
        opacity_map = {'0%': 0.0, '25%': 0.25, '50%': 0.50, '75%': 0.75, '100%': 1.0}
        self.bg_opacity = opacity_map.get(opacity_str, 0.50)

    def update_background_label(self):
        """Update background label size and pixmap"""
        if not hasattr(self, 'bg_label'):
            return

        # Check if background should be shown
        if not self.settings.get('show_background', True) or not self.background_pixmap:
            self.bg_label.clear()
            return

        central = self.centralWidget()
        if central:
            self.bg_label.setGeometry(0, 0, central.width(), central.height())
            scaled = self.background_pixmap.scaled(
                central.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            # Apply opacity by painting onto a transparent pixmap
            transparent = QPixmap(scaled.size())
            transparent.fill(Qt.transparent)
            painter = QPainter(transparent)
            painter.setOpacity(self.bg_opacity)
            painter.drawPixmap(0, 0, scaled)
            painter.end()
            self.bg_label.setPixmap(transparent)
    
    def start_listener(self):
        """Start the keyboard listener thread"""
        self.listener_thread = KeyboardListener(self.snippets, self.settings)
        self.listener_thread.trigger_detected.connect(self.handle_trigger)
        self.listener_thread.start()

    def show_tutorial(self):
        """Show the first-run tutorial dialog"""
        dialog = TutorialDialog(self)
        result = dialog.exec_()

        # Mark tutorial as completed if user finished or checked "don't show again"
        if dialog.dont_show_again or result == QDialog.Accepted:
            self.settings['tutorial_completed'] = True
            self.save_settings()

    def load_snippets(self):
        """Load snippets from config file (backward compatible with folder field)"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    snippets = json.load(f)
                    # Ensure each snippet has a folder field (default to "General")
                    for snippet in snippets:
                        if 'folder' not in snippet or not snippet['folder']:
                            snippet['folder'] = 'General'
                    return snippets
            except:
                return []
        return []

    def load_folders(self):
        """Load custom folders list"""
        if self.folders_file.exists():
            try:
                with open(self.folders_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []

    def save_snippets(self):
        """Save snippets to config file"""
        # Ensure each snippet has a folder field before saving
        for snippet in self.snippets:
            if 'folder' not in snippet or not snippet['folder']:
                snippet['folder'] = 'General'
        with open(self.config_file, 'w') as f:
            json.dump(self.snippets, f, indent=2)
        self.listener_thread.update_snippets(self.snippets)

    def save_folders(self):
        """Save custom folders list"""
        with open(self.folders_file, 'w') as f:
            json.dump(self.custom_folders, f, indent=2)

    def load_settings(self):
        """Load application settings"""
        default_settings = {
            # Appearance
            'theme': 'Dark',
            'show_background': True,
            'custom_background': '',
            'custom_background_light': '',
            'background_opacity': '25%',
            'font_size': 14,
            # Behavior
            'start_minimized': True,
            'start_on_login': False,
            'play_sound': False,
            'show_notification': False,
            'expansion_delay': 50,
            # Triggers
            'case_sensitive': True,
            'require_delimiter': False,
            'require_prefix': False,
            'prefix_char': '/',
            'clear_clipboard': False,
            # Date/Time
            'date_format': 'MM/DD/YYYY',
            'time_format': '12-hour (3:30 PM)',
            'first_day_of_week': 'Sunday',
            # Backup
            'auto_backup': False,
            'backup_path': '',
            # Tutorial
            'tutorial_completed': False,
        }
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r') as f:
                    saved = json.load(f)
                    # Merge with defaults in case new settings are added
                    default_settings.update(saved)
            except:
                pass
        return default_settings

    def save_settings(self):
        """Save application settings"""
        with open(self.settings_file, 'w') as f:
            json.dump(self.settings, f, indent=2)

    def load_emoji_favorites(self):
        """Load user's favorite emojis list"""
        if self.emoji_favorites_file.exists():
            try:
                with open(self.emoji_favorites_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []

    def save_emoji_favorites(self, favorites_list):
        """Save user's favorite emojis list"""
        with open(self.emoji_favorites_file, 'w') as f:
            json.dump(favorites_list, f, indent=2)

    def load_custom_emojis(self):
        """Load custom emoji metadata"""
        if self.custom_emojis_file.exists():
            try:
                with open(self.custom_emojis_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []

    def save_custom_emojis(self, emojis_data):
        """Save custom emoji metadata"""
        with open(self.custom_emojis_file, 'w') as f:
            json.dump(emojis_data, f, indent=2)

    def build_emoji_database(self):
        """Build categorized emoji database with curated popular emojis (~400 total)"""
        # Return cached data if available
        if self._emoji_database_cache is not None:
            return self._emoji_database_cache, self._emoji_search_index_cache, self._emoji_categories_cache

        # Category definitions with icons
        EMOJI_CATEGORIES = [
            ('favorites', '⭐', 'Favorites'),
            ('smileys_emotion', '😀', 'Smileys & Faces'),
            ('people_body', '👋', 'Gestures & People'),
            ('animals_nature', '🐻', 'Animals & Nature'),
            ('food_drink', '🍔', 'Food & Drink'),
            ('travel_places', '🚗', 'Travel & Places'),
            ('activities', '⚽', 'Activities'),
            ('objects', '💡', 'Objects'),
            ('symbols', '❤️', 'Symbols'),
            ('custom', '➕', 'Custom'),
        ]

        # Curated popular emojis with search terms
        # Format: (emoji, 'search terms separated by spaces')
        EMOJI_DATA = {
            'smileys_emotion': [
                # Happy faces
                ('😀', 'grinning happy smile'),
                ('😃', 'smiley happy grin'),
                ('😄', 'smile happy laugh'),
                ('😁', 'grin beaming happy'),
                ('😆', 'laughing happy haha'),
                ('😅', 'sweat nervous laugh'),
                ('🤣', 'rofl rolling laughing'),
                ('😂', 'joy tears laughing crying'),
                ('🙂', 'slightly smiling'),
                ('🙃', 'upside down'),
                ('😉', 'wink winking'),
                ('😊', 'blush happy shy'),
                ('😇', 'innocent angel halo'),
                # Love faces
                ('🥰', 'love hearts smiling'),
                ('😍', 'heart eyes love'),
                ('🤩', 'star struck excited'),
                ('😘', 'kiss blowing'),
                ('😗', 'kissing'),
                ('😚', 'kissing closed eyes'),
                ('😙', 'kissing smiling'),
                ('🥲', 'smiling tear happy sad'),
                # Playful faces
                ('😋', 'yummy delicious tongue'),
                ('😛', 'tongue out playful'),
                ('😜', 'wink tongue crazy'),
                ('🤪', 'zany crazy wild'),
                ('😝', 'squinting tongue'),
                ('🤑', 'money face rich'),
                # Caring faces
                ('🤗', 'hugging hug'),
                ('🤭', 'hand over mouth giggle'),
                ('🤫', 'shushing quiet secret'),
                ('🤔', 'thinking hmm'),
                ('🤐', 'zipper mouth quiet'),
                # Neutral/skeptical
                ('🤨', 'raised eyebrow skeptical'),
                ('😐', 'neutral face'),
                ('😑', 'expressionless blank'),
                ('😶', 'no mouth silent'),
                ('😏', 'smirk smug'),
                ('😒', 'unamused annoyed'),
                ('🙄', 'eye roll annoyed'),
                ('😬', 'grimacing awkward'),
                ('🤥', 'lying pinocchio'),
                # Sleepy/sick
                ('😌', 'relieved peaceful'),
                ('😔', 'pensive sad thoughtful'),
                ('😪', 'sleepy tired'),
                ('🤤', 'drooling'),
                ('😴', 'sleeping zzz'),
                ('😷', 'mask sick'),
                ('🤒', 'thermometer sick fever'),
                ('🤕', 'bandage hurt injured'),
                ('🤢', 'nauseated sick green'),
                ('🤮', 'vomiting sick'),
                ('🤧', 'sneezing sick'),
                ('🥵', 'hot sweating'),
                ('🥶', 'cold freezing'),
                ('🥴', 'woozy drunk dizzy'),
                ('😵', 'dizzy knocked out'),
                ('🤯', 'exploding head mind blown'),
                # Cool/party
                ('🤠', 'cowboy hat yeehaw'),
                ('🥳', 'party celebration'),
                ('🥸', 'disguise glasses'),
                ('😎', 'sunglasses cool'),
                ('🤓', 'nerd glasses'),
                ('🧐', 'monocle fancy'),
                # Sad/crying
                ('😕', 'confused'),
                ('😟', 'worried'),
                ('🙁', 'slightly frowning'),
                ('☹️', 'frowning sad'),
                ('😮', 'open mouth surprised'),
                ('😯', 'hushed surprised'),
                ('😲', 'astonished shocked'),
                ('😳', 'flushed embarrassed'),
                ('🥺', 'pleading puppy eyes'),
                ('😦', 'frowning open mouth'),
                ('😧', 'anguished'),
                ('😨', 'fearful scared'),
                ('😰', 'anxious sweat'),
                ('😥', 'sad relieved'),
                ('😢', 'crying tear'),
                ('😭', 'sobbing crying loud'),
                ('😱', 'screaming fear'),
                ('😖', 'confounded'),
                ('😣', 'persevering'),
                ('😞', 'disappointed sad'),
                ('😓', 'downcast sweat'),
                ('😩', 'weary tired'),
                ('😫', 'tired exhausted'),
                ('🥱', 'yawning tired'),
                # Angry faces
                ('😤', 'triumph huffing'),
                ('😡', 'pouting angry red'),
                ('😠', 'angry mad'),
                ('🤬', 'cursing swearing symbols'),
                ('👿', 'angry devil imp'),
                ('💀', 'skull dead'),
                ('☠️', 'skull crossbones death'),
                # Fantasy faces
                ('💩', 'poop poo'),
                ('🤡', 'clown'),
                ('👹', 'ogre monster'),
                ('👺', 'goblin tengu'),
                ('👻', 'ghost boo'),
                ('👽', 'alien extraterrestrial'),
                ('👾', 'alien monster space invader'),
                ('🤖', 'robot'),
                ('😺', 'cat happy smiling'),
                ('😸', 'cat grinning'),
                ('😹', 'cat joy tears'),
                ('😻', 'cat heart eyes love'),
                ('😼', 'cat smirk wry'),
                ('😽', 'cat kissing'),
                ('🙀', 'cat weary shocked'),
                ('😿', 'cat crying sad'),
                ('😾', 'cat pouting angry'),
                # Monkey faces
                ('🙈', 'see no evil monkey'),
                ('🙉', 'hear no evil monkey'),
                ('🙊', 'speak no evil monkey'),
                # Hearts
                ('❤️', 'red heart love'),
                ('🧡', 'orange heart'),
                ('💛', 'yellow heart'),
                ('💚', 'green heart'),
                ('💙', 'blue heart'),
                ('💜', 'purple heart'),
                ('🖤', 'black heart'),
                ('🤍', 'white heart'),
                ('🤎', 'brown heart'),
                ('💔', 'broken heart'),
                ('❤️‍🔥', 'heart fire burning'),
                ('❤️‍🩹', 'mending heart healing'),
                ('💕', 'two hearts love'),
                ('💞', 'revolving hearts'),
                ('💓', 'beating heart'),
                ('💗', 'growing heart'),
                ('💖', 'sparkling heart'),
                ('💘', 'heart arrow cupid'),
                ('💝', 'heart ribbon gift'),
                ('💟', 'heart decoration'),
                ('💌', 'love letter'),
                ('💋', 'kiss mark lips'),
                ('💯', 'hundred points perfect'),
                ('💢', 'anger symbol'),
                ('💥', 'collision boom explosion'),
                ('💫', 'dizzy star'),
                ('💦', 'sweat droplets'),
                ('💨', 'dashing away wind'),
                ('🕳️', 'hole'),
                ('💬', 'speech bubble'),
                ('💭', 'thought bubble'),
                ('🗯️', 'anger bubble'),
                ('💤', 'zzz sleeping'),
            ],
            'people_body': [
                # Hands
                ('👋', 'wave waving hello bye'),
                ('🤚', 'raised back hand'),
                ('🖐️', 'hand fingers splayed'),
                ('✋', 'raised hand stop high five'),
                ('🖖', 'vulcan salute spock'),
                ('👌', 'ok okay perfect'),
                ('🤌', 'pinched fingers italian'),
                ('🤏', 'pinching small'),
                ('✌️', 'victory peace'),
                ('🤞', 'crossed fingers luck'),
                ('🤟', 'love you gesture'),
                ('🤘', 'rock on horns metal'),
                ('🤙', 'call me hand shaka'),
                ('👈', 'pointing left'),
                ('👉', 'pointing right'),
                ('👆', 'pointing up'),
                ('🖕', 'middle finger'),
                ('👇', 'pointing down'),
                ('☝️', 'index pointing up'),
                ('👍', 'thumbs up like yes'),
                ('👎', 'thumbs down dislike no'),
                ('✊', 'raised fist'),
                ('👊', 'fist bump punch'),
                ('🤛', 'left facing fist'),
                ('🤜', 'right facing fist'),
                ('👏', 'clapping applause'),
                ('🙌', 'raising hands celebration'),
                ('👐', 'open hands'),
                ('🤲', 'palms up together'),
                ('🤝', 'handshake deal'),
                ('🙏', 'pray please thanks folded hands'),
                ('✍️', 'writing hand'),
                ('💅', 'nail polish'),
                ('🤳', 'selfie'),
                ('💪', 'flexed biceps strong muscle'),
                # Body parts
                ('👂', 'ear listening'),
                ('👃', 'nose smell'),
                ('👀', 'eyes looking'),
                ('👁️', 'eye'),
                ('👅', 'tongue'),
                ('👄', 'mouth lips'),
                # People
                ('👶', 'baby'),
                ('🧒', 'child kid'),
                ('👦', 'boy'),
                ('👧', 'girl'),
                ('🧑', 'person adult'),
                ('👨', 'man'),
                ('👩', 'woman'),
                ('🧓', 'older person'),
                ('👴', 'old man grandfather'),
                ('👵', 'old woman grandmother'),
                # Professional people
                ('👨‍💻', 'man technologist programmer'),
                ('👩‍💻', 'woman technologist programmer'),
                ('👨‍🔬', 'man scientist'),
                ('👩‍🔬', 'woman scientist'),
                ('👨‍🎨', 'man artist'),
                ('👩‍🎨', 'woman artist'),
                ('👨‍🚀', 'man astronaut'),
                ('👩‍🚀', 'woman astronaut'),
                ('👮', 'police officer cop'),
                ('🕵️', 'detective spy'),
                ('💂', 'guard'),
                ('🥷', 'ninja'),
                ('👷', 'construction worker'),
                ('🤴', 'prince'),
                ('👸', 'princess'),
                ('🧙', 'mage wizard'),
                ('🧚', 'fairy'),
                ('🧛', 'vampire'),
                ('🧜', 'merperson mermaid'),
                ('🧝', 'elf'),
                ('🧞', 'genie'),
                ('🧟', 'zombie'),
                ('🦸', 'superhero'),
                ('🦹', 'supervillain'),
                # Gestures
                ('🙍', 'person frowning'),
                ('🙎', 'person pouting'),
                ('🙅', 'person gesturing no'),
                ('🙆', 'person gesturing ok'),
                ('💁', 'person tipping hand'),
                ('🙋', 'person raising hand'),
                ('🧏', 'deaf person'),
                ('🙇', 'person bowing'),
                ('🤦', 'facepalm'),
                ('🤷', 'shrug idk'),
                # Activities
                ('💃', 'woman dancing'),
                ('🕺', 'man dancing'),
                ('👯', 'people bunny ears'),
                ('🧘', 'person lotus yoga meditation'),
                ('🛀', 'person bath'),
                ('🛌', 'person bed sleeping'),
                # Family & couples
                ('👫', 'man woman holding hands couple'),
                ('👭', 'women holding hands'),
                ('👬', 'men holding hands'),
                ('💏', 'kiss couple'),
                ('💑', 'couple heart love'),
                ('👪', 'family'),
            ],
            'animals_nature': [
                # Mammals
                ('🐶', 'dog face puppy'),
                ('🐕', 'dog'),
                ('🐩', 'poodle dog'),
                ('🐺', 'wolf'),
                ('🦊', 'fox'),
                ('🦝', 'raccoon'),
                ('🐱', 'cat face kitty'),
                ('🐈', 'cat'),
                ('🦁', 'lion'),
                ('🐯', 'tiger face'),
                ('🐅', 'tiger'),
                ('🐆', 'leopard'),
                ('🐴', 'horse face'),
                ('🐎', 'horse racing'),
                ('🦄', 'unicorn'),
                ('🐮', 'cow face'),
                ('🐂', 'ox'),
                ('🐃', 'water buffalo'),
                ('🐄', 'cow'),
                ('🐷', 'pig face'),
                ('🐖', 'pig'),
                ('🐗', 'boar'),
                ('🐽', 'pig nose'),
                ('🐏', 'ram sheep'),
                ('🐑', 'ewe sheep'),
                ('🐐', 'goat'),
                ('🐪', 'camel'),
                ('🐫', 'two hump camel'),
                ('🦙', 'llama alpaca'),
                ('🐘', 'elephant'),
                ('🦏', 'rhinoceros'),
                ('🦛', 'hippo hippopotamus'),
                ('🐭', 'mouse face'),
                ('🐁', 'mouse'),
                ('🐀', 'rat'),
                ('🐹', 'hamster'),
                ('🐰', 'rabbit face bunny'),
                ('🐇', 'rabbit bunny'),
                ('🐿️', 'chipmunk squirrel'),
                ('🦔', 'hedgehog'),
                ('🦇', 'bat'),
                ('🐻', 'bear'),
                ('🐻‍❄️', 'polar bear'),
                ('🐨', 'koala'),
                ('🐼', 'panda'),
                ('🦥', 'sloth'),
                ('🦦', 'otter'),
                ('🦨', 'skunk'),
                ('🦘', 'kangaroo'),
                ('🦡', 'badger'),
                # Birds
                ('🐔', 'chicken'),
                ('🐓', 'rooster'),
                ('🐣', 'hatching chick'),
                ('🐤', 'baby chick'),
                ('🐥', 'front facing chick'),
                ('🐦', 'bird'),
                ('🐧', 'penguin'),
                ('🕊️', 'dove peace'),
                ('🦅', 'eagle'),
                ('🦆', 'duck'),
                ('🦢', 'swan'),
                ('🦉', 'owl'),
                ('🦩', 'flamingo'),
                ('🦚', 'peacock'),
                ('🦜', 'parrot'),
                # Marine & reptiles
                ('🐸', 'frog'),
                ('🐊', 'crocodile'),
                ('🐢', 'turtle'),
                ('🦎', 'lizard'),
                ('🐍', 'snake'),
                ('🐲', 'dragon face'),
                ('🐉', 'dragon'),
                ('🦕', 'dinosaur sauropod'),
                ('🦖', 'dinosaur t-rex'),
                ('🐳', 'whale spouting'),
                ('🐋', 'whale'),
                ('🐬', 'dolphin'),
                ('🦭', 'seal'),
                ('🐟', 'fish'),
                ('🐠', 'tropical fish'),
                ('🐡', 'blowfish'),
                ('🦈', 'shark'),
                ('🐙', 'octopus'),
                ('🐚', 'shell'),
                # Bugs
                ('🐌', 'snail'),
                ('🦋', 'butterfly'),
                ('🐛', 'bug caterpillar'),
                ('🐜', 'ant'),
                ('🐝', 'bee honeybee'),
                ('🪲', 'beetle'),
                ('🐞', 'ladybug'),
                ('🦗', 'cricket'),
                ('🪳', 'cockroach'),
                ('🕷️', 'spider'),
                ('🕸️', 'spider web'),
                ('🦂', 'scorpion'),
                # Plants
                ('💐', 'bouquet flowers'),
                ('🌸', 'cherry blossom'),
                ('💮', 'white flower'),
                ('🌹', 'rose'),
                ('🥀', 'wilted flower'),
                ('🌺', 'hibiscus'),
                ('🌻', 'sunflower'),
                ('🌼', 'blossom'),
                ('🌷', 'tulip'),
                ('🌱', 'seedling'),
                ('🌲', 'evergreen tree'),
                ('🌳', 'deciduous tree'),
                ('🌴', 'palm tree'),
                ('🌵', 'cactus'),
                ('🌾', 'sheaf rice'),
                ('🌿', 'herb'),
                ('☘️', 'shamrock'),
                ('🍀', 'four leaf clover lucky'),
                ('🍁', 'maple leaf fall autumn'),
                ('🍂', 'fallen leaf autumn'),
                ('🍃', 'leaf fluttering wind'),
                ('🪴', 'potted plant'),
            ],
            'food_drink': [
                # Fruits
                ('🍇', 'grapes'),
                ('🍈', 'melon'),
                ('🍉', 'watermelon'),
                ('🍊', 'tangerine orange'),
                ('🍋', 'lemon'),
                ('🍌', 'banana'),
                ('🍍', 'pineapple'),
                ('🥭', 'mango'),
                ('🍎', 'red apple'),
                ('🍏', 'green apple'),
                ('🍐', 'pear'),
                ('🍑', 'peach'),
                ('🍒', 'cherries'),
                ('🍓', 'strawberry'),
                ('🫐', 'blueberries'),
                ('🥝', 'kiwi'),
                ('🍅', 'tomato'),
                ('🥥', 'coconut'),
                ('🥑', 'avocado'),
                # Vegetables
                ('🍆', 'eggplant aubergine'),
                ('🥔', 'potato'),
                ('🥕', 'carrot'),
                ('🌽', 'corn'),
                ('🌶️', 'hot pepper chili'),
                ('🥒', 'cucumber'),
                ('🥬', 'leafy green'),
                ('🥦', 'broccoli'),
                ('🧄', 'garlic'),
                ('🧅', 'onion'),
                ('🍄', 'mushroom'),
                # Prepared food
                ('🍞', 'bread'),
                ('🥐', 'croissant'),
                ('🥖', 'baguette bread'),
                ('🥨', 'pretzel'),
                ('🧀', 'cheese'),
                ('🥚', 'egg'),
                ('🍳', 'cooking egg fried'),
                ('🧈', 'butter'),
                ('🥞', 'pancakes'),
                ('🧇', 'waffle'),
                ('🥓', 'bacon'),
                ('🥩', 'cut meat steak'),
                ('🍗', 'poultry leg chicken'),
                ('🍖', 'meat bone'),
                ('🌭', 'hot dog'),
                ('🍔', 'hamburger burger'),
                ('🍟', 'french fries'),
                ('🍕', 'pizza'),
                ('🥪', 'sandwich'),
                ('🥙', 'pita stuffed flatbread'),
                ('🧆', 'falafel'),
                ('🌮', 'taco'),
                ('🌯', 'burrito'),
                ('🥗', 'salad'),
                ('🍝', 'spaghetti pasta'),
                ('🍜', 'steaming bowl noodles ramen'),
                ('🍲', 'pot food stew'),
                ('🍛', 'curry rice'),
                ('🍣', 'sushi'),
                ('🍱', 'bento box'),
                ('🥟', 'dumpling'),
                ('🍤', 'fried shrimp'),
                ('🍙', 'rice ball'),
                ('🍚', 'cooked rice'),
                ('🍘', 'rice cracker'),
                # Sweets
                ('🍦', 'soft ice cream'),
                ('🍧', 'shaved ice'),
                ('🍨', 'ice cream'),
                ('🍩', 'doughnut donut'),
                ('🍪', 'cookie'),
                ('🎂', 'birthday cake'),
                ('🍰', 'shortcake slice'),
                ('🧁', 'cupcake'),
                ('🥧', 'pie'),
                ('🍫', 'chocolate bar'),
                ('🍬', 'candy'),
                ('🍭', 'lollipop'),
                ('🍮', 'custard pudding'),
                ('🍯', 'honey pot'),
                # Drinks
                ('🍼', 'baby bottle'),
                ('🥛', 'glass milk'),
                ('☕', 'coffee hot beverage'),
                ('🫖', 'teapot'),
                ('🍵', 'tea cup'),
                ('🧃', 'juice box'),
                ('🥤', 'cup straw'),
                ('🧋', 'bubble tea boba'),
                ('🍶', 'sake'),
                ('🍾', 'champagne bottle'),
                ('🍷', 'wine glass'),
                ('🍸', 'cocktail glass martini'),
                ('🍹', 'tropical drink'),
                ('🍺', 'beer mug'),
                ('🍻', 'clinking beer mugs cheers'),
                ('🥂', 'clinking glasses champagne'),
                ('🥃', 'whisky tumbler'),
                # Utensils
                ('🥄', 'spoon'),
                ('🍴', 'fork knife'),
                ('🍽️', 'plate cutlery'),
            ],
            'travel_places': [
                # Transport ground
                ('🚗', 'car automobile'),
                ('🚕', 'taxi cab'),
                ('🚙', 'suv sport utility'),
                ('🚌', 'bus'),
                ('🚎', 'trolleybus'),
                ('🏎️', 'racing car'),
                ('🚓', 'police car'),
                ('🚑', 'ambulance'),
                ('🚒', 'fire engine truck'),
                ('🚐', 'minibus'),
                ('🚚', 'delivery truck'),
                ('🚛', 'articulated lorry'),
                ('🚜', 'tractor'),
                ('🛴', 'kick scooter'),
                ('🚲', 'bicycle bike'),
                ('🛵', 'motor scooter'),
                ('🏍️', 'motorcycle'),
                ('🚃', 'railway car train'),
                ('🚋', 'tram streetcar'),
                ('🚇', 'metro subway'),
                ('🚆', 'train'),
                ('🚂', 'locomotive steam'),
                ('🚈', 'light rail'),
                ('🚊', 'tram'),
                # Transport air
                ('✈️', 'airplane plane'),
                ('🛫', 'airplane departure takeoff'),
                ('🛬', 'airplane arrival landing'),
                ('💺', 'seat'),
                ('🚁', 'helicopter'),
                ('🚀', 'rocket'),
                ('🛸', 'flying saucer ufo'),
                # Transport water
                ('⛵', 'sailboat'),
                ('🚤', 'speedboat'),
                ('🛥️', 'motor boat'),
                ('🛳️', 'passenger ship cruise'),
                ('⛴️', 'ferry'),
                ('🚢', 'ship'),
                # Places
                ('🏠', 'house home'),
                ('🏡', 'house garden'),
                ('🏢', 'office building'),
                ('🏣', 'post office'),
                ('🏥', 'hospital'),
                ('🏦', 'bank'),
                ('🏨', 'hotel'),
                ('🏩', 'love hotel'),
                ('🏪', 'convenience store'),
                ('🏫', 'school'),
                ('🏬', 'department store'),
                ('🏭', 'factory'),
                ('🏯', 'japanese castle'),
                ('🏰', 'castle'),
                ('💒', 'wedding chapel'),
                ('🗼', 'tokyo tower'),
                ('🗽', 'statue liberty'),
                ('⛪', 'church'),
                ('🕌', 'mosque'),
                ('🛕', 'hindu temple'),
                ('🕍', 'synagogue'),
                ('⛩️', 'shinto shrine'),
                ('🕋', 'kaaba'),
                ('⛲', 'fountain'),
                ('⛺', 'tent camping'),
                ('🌁', 'foggy'),
                ('🌃', 'night stars'),
                ('🏙️', 'cityscape'),
                ('🌄', 'sunrise mountains'),
                ('🌅', 'sunrise'),
                ('🌆', 'cityscape dusk'),
                ('🌇', 'sunset'),
                ('🌉', 'bridge night'),
                # Nature places
                ('🏔️', 'snow capped mountain'),
                ('⛰️', 'mountain'),
                ('🌋', 'volcano'),
                ('🗻', 'mount fuji'),
                ('🏕️', 'camping'),
                ('🏖️', 'beach umbrella'),
                ('🏜️', 'desert'),
                ('🏝️', 'desert island'),
                ('🏞️', 'national park'),
                # Sky & weather
                ('🌍', 'earth globe europe africa'),
                ('🌎', 'earth globe americas'),
                ('🌏', 'earth globe asia australia'),
                ('🌐', 'globe meridians'),
                ('🌑', 'new moon'),
                ('🌒', 'waxing crescent moon'),
                ('🌓', 'first quarter moon'),
                ('🌔', 'waxing gibbous moon'),
                ('🌕', 'full moon'),
                ('🌖', 'waning gibbous moon'),
                ('🌗', 'last quarter moon'),
                ('🌘', 'waning crescent moon'),
                ('🌙', 'crescent moon'),
                ('🌚', 'new moon face'),
                ('🌛', 'first quarter moon face'),
                ('🌜', 'last quarter moon face'),
                ('🌝', 'full moon face'),
                ('🌞', 'sun face'),
                ('⭐', 'star'),
                ('🌟', 'glowing star'),
                ('✨', 'sparkles'),
                ('💫', 'dizzy star'),
                ('☀️', 'sun sunny'),
                ('🌤️', 'sun small cloud'),
                ('⛅', 'sun behind cloud'),
                ('🌥️', 'sun behind large cloud'),
                ('🌦️', 'sun behind rain cloud'),
                ('🌧️', 'cloud rain'),
                ('⛈️', 'cloud lightning rain'),
                ('🌩️', 'cloud lightning'),
                ('🌨️', 'cloud snow'),
                ('☁️', 'cloud'),
                ('🌪️', 'tornado'),
                ('🌫️', 'fog'),
                ('🌬️', 'wind face'),
                ('🌈', 'rainbow'),
                ('☔', 'umbrella rain'),
                ('⚡', 'lightning zap'),
                ('❄️', 'snowflake'),
                ('☃️', 'snowman'),
                ('⛄', 'snowman without snow'),
                ('🔥', 'fire flame hot'),
                ('💧', 'droplet water'),
                ('🌊', 'wave water ocean'),
            ],
            'activities': [
                # Sports
                ('⚽', 'soccer football'),
                ('🏀', 'basketball'),
                ('🏈', 'american football'),
                ('⚾', 'baseball'),
                ('🥎', 'softball'),
                ('🎾', 'tennis'),
                ('🏐', 'volleyball'),
                ('🏉', 'rugby'),
                ('🥏', 'flying disc frisbee'),
                ('🎱', 'pool 8 ball billiards'),
                ('🪀', 'yo-yo'),
                ('🏓', 'ping pong table tennis'),
                ('🏸', 'badminton'),
                ('🏒', 'ice hockey'),
                ('🏑', 'field hockey'),
                ('🥍', 'lacrosse'),
                ('🏏', 'cricket'),
                ('🥅', 'goal net'),
                ('⛳', 'golf flag hole'),
                ('🪁', 'kite'),
                ('🏹', 'bow arrow archery'),
                ('🎣', 'fishing'),
                ('🤿', 'diving mask'),
                ('🥊', 'boxing glove'),
                ('🥋', 'martial arts uniform'),
                ('🎿', 'skis skiing'),
                ('🛷', 'sled'),
                ('🥌', 'curling stone'),
                ('🛹', 'skateboard'),
                ('🛼', 'roller skate'),
                ('🏋️', 'person lifting weights'),
                ('🤸', 'person cartwheeling'),
                ('🤺', 'person fencing'),
                ('⛷️', 'skier'),
                ('🏂', 'snowboarder'),
                ('🧗', 'person climbing'),
                ('🏄', 'person surfing'),
                ('🚣', 'person rowing boat'),
                ('🏊', 'person swimming'),
                ('🚴', 'person biking'),
                ('🚵', 'person mountain biking'),
                ('🧘', 'person lotus position yoga'),
                # Games
                ('🎮', 'video game controller'),
                ('🕹️', 'joystick'),
                ('🎰', 'slot machine'),
                ('🎲', 'dice game'),
                ('🧩', 'puzzle piece'),
                ('🎯', 'bullseye target dart'),
                ('🎳', 'bowling'),
                ('🎪', 'circus tent'),
                ('🎭', 'performing arts theater'),
                ('🎨', 'artist palette paint'),
                ('🖼️', 'framed picture'),
                ('🎼', 'musical score'),
                ('🎵', 'musical note'),
                ('🎶', 'musical notes'),
                ('🎹', 'musical keyboard piano'),
                ('🥁', 'drum'),
                ('🎷', 'saxophone'),
                ('🎺', 'trumpet'),
                ('🎸', 'guitar'),
                ('🪕', 'banjo'),
                ('🎻', 'violin'),
                ('🎬', 'clapper board movie'),
                ('🎤', 'microphone karaoke'),
                ('🎧', 'headphone'),
                ('📻', 'radio'),
                # Celebration
                ('🎀', 'ribbon'),
                ('🎁', 'gift present wrapped'),
                ('🎂', 'birthday cake'),
                ('🎄', 'christmas tree'),
                ('🎃', 'jack o lantern pumpkin halloween'),
                ('🎆', 'fireworks'),
                ('🎇', 'sparkler'),
                ('🎉', 'party popper celebration'),
                ('🎊', 'confetti ball'),
                ('🏆', 'trophy winner'),
                ('🏅', 'sports medal'),
                ('🥇', 'first place medal gold'),
                ('🥈', 'second place medal silver'),
                ('🥉', 'third place medal bronze'),
            ],
            'objects': [
                # Tech
                ('⌚', 'watch'),
                ('📱', 'mobile phone smartphone'),
                ('📲', 'mobile phone arrow'),
                ('💻', 'laptop computer'),
                ('🖥️', 'desktop computer'),
                ('🖨️', 'printer'),
                ('⌨️', 'keyboard'),
                ('🖱️', 'computer mouse'),
                ('🖲️', 'trackball'),
                ('💾', 'floppy disk'),
                ('💿', 'optical disk cd'),
                ('📀', 'dvd'),
                ('📷', 'camera'),
                ('📸', 'camera flash'),
                ('📹', 'video camera'),
                ('🎥', 'movie camera'),
                ('📽️', 'film projector'),
                ('📺', 'television tv'),
                ('📞', 'telephone receiver'),
                ('☎️', 'telephone'),
                ('📟', 'pager'),
                ('📠', 'fax machine'),
                ('🔋', 'battery'),
                ('🔌', 'electric plug'),
                # Light
                ('💡', 'light bulb idea'),
                ('🔦', 'flashlight'),
                ('🕯️', 'candle'),
                # Office
                ('📔', 'notebook decorative'),
                ('📕', 'closed book'),
                ('📖', 'open book'),
                ('📗', 'green book'),
                ('📘', 'blue book'),
                ('📙', 'orange book'),
                ('📚', 'books'),
                ('📓', 'notebook'),
                ('📒', 'ledger'),
                ('📃', 'page curl'),
                ('📜', 'scroll'),
                ('📄', 'page facing up document'),
                ('📰', 'newspaper'),
                ('📑', 'bookmark tabs'),
                ('🔖', 'bookmark'),
                ('🏷️', 'label tag'),
                ('✉️', 'envelope email'),
                ('📧', 'e-mail'),
                ('📨', 'incoming envelope'),
                ('📩', 'envelope arrow'),
                ('📤', 'outbox tray'),
                ('📥', 'inbox tray'),
                ('📦', 'package box'),
                ('📫', 'mailbox'),
                ('📪', 'mailbox lowered flag'),
                ('📬', 'mailbox raised flag'),
                ('📭', 'mailbox no mail'),
                ('📮', 'postbox'),
                ('✏️', 'pencil'),
                ('✒️', 'black nib'),
                ('🖊️', 'pen'),
                ('🖋️', 'fountain pen'),
                ('🖌️', 'paintbrush'),
                ('🖍️', 'crayon'),
                ('📝', 'memo note'),
                ('📁', 'file folder'),
                ('📂', 'open file folder'),
                ('🗂️', 'card index dividers'),
                ('📅', 'calendar'),
                ('📆', 'tear off calendar'),
                ('🗓️', 'spiral calendar'),
                ('📇', 'card index'),
                ('📈', 'chart increasing'),
                ('📉', 'chart decreasing'),
                ('📊', 'bar chart'),
                ('📋', 'clipboard'),
                ('📌', 'pushpin'),
                ('📍', 'round pushpin'),
                ('📎', 'paperclip'),
                ('🖇️', 'linked paperclips'),
                ('📏', 'straight ruler'),
                ('📐', 'triangular ruler'),
                ('✂️', 'scissors'),
                ('🗃️', 'card file box'),
                ('🗄️', 'file cabinet'),
                ('🗑️', 'wastebasket trash'),
                # Lock
                ('🔒', 'locked'),
                ('🔓', 'unlocked'),
                ('🔏', 'locked pen'),
                ('🔐', 'locked key'),
                ('🔑', 'key'),
                ('🗝️', 'old key'),
                # Tools
                ('🔨', 'hammer'),
                ('🪓', 'axe'),
                ('⛏️', 'pick'),
                ('🔧', 'wrench'),
                ('🔩', 'nut bolt'),
                ('⚙️', 'gear'),
                ('🗜️', 'clamp'),
                ('🪛', 'screwdriver'),
                ('🔗', 'link chain'),
                ('⛓️', 'chains'),
                ('🪝', 'hook'),
                ('🧲', 'magnet'),
                ('🧰', 'toolbox'),
                # Medical
                ('💉', 'syringe injection'),
                ('🩸', 'drop blood'),
                ('💊', 'pill medicine'),
                ('🩹', 'bandage'),
                ('🩺', 'stethoscope'),
                # Household
                ('🚪', 'door'),
                ('🛏️', 'bed'),
                ('🛋️', 'couch lamp'),
                ('🪑', 'chair'),
                ('🚽', 'toilet'),
                ('🚿', 'shower'),
                ('🛁', 'bathtub'),
                ('🧴', 'lotion bottle'),
                ('🧷', 'safety pin'),
                ('🧹', 'broom'),
                ('🧺', 'basket'),
                ('🧻', 'roll paper toilet'),
                ('🧼', 'soap'),
                ('🧽', 'sponge'),
                ('🧯', 'fire extinguisher'),
                ('🛒', 'shopping cart'),
                # Other objects
                ('🎈', 'balloon'),
                ('🎏', 'carp streamer'),
                ('🎐', 'wind chime'),
                ('🪄', 'magic wand'),
                ('🔮', 'crystal ball'),
                ('🧿', 'nazar amulet evil eye'),
                ('💎', 'gem stone diamond'),
                ('🔔', 'bell'),
                ('🔕', 'bell slash no sound'),
                ('🎵', 'musical note'),
                ('🎶', 'musical notes'),
            ],
            'symbols': [
                # Hearts (some duplicated from smileys for discoverability)
                ('❤️', 'red heart love'),
                ('🧡', 'orange heart'),
                ('💛', 'yellow heart'),
                ('💚', 'green heart'),
                ('💙', 'blue heart'),
                ('💜', 'purple heart'),
                ('🖤', 'black heart'),
                ('🤍', 'white heart'),
                ('🤎', 'brown heart'),
                ('💔', 'broken heart'),
                # Shapes & symbols
                ('💯', 'hundred points perfect score'),
                ('✅', 'check mark button yes done'),
                ('☑️', 'check box'),
                ('✔️', 'check mark'),
                ('❌', 'cross mark no wrong'),
                ('❎', 'cross mark button'),
                ('➕', 'plus'),
                ('➖', 'minus'),
                ('➗', 'divide'),
                ('✖️', 'multiply'),
                ('♾️', 'infinity'),
                ('❗', 'exclamation mark'),
                ('❓', 'question mark'),
                ('❕', 'white exclamation'),
                ('❔', 'white question'),
                ('‼️', 'double exclamation'),
                ('⁉️', 'exclamation question'),
                ('💲', 'dollar sign'),
                ('⚠️', 'warning'),
                ('🚫', 'prohibited no'),
                ('🔞', 'no one under eighteen'),
                ('📵', 'no mobile phones'),
                ('🔇', 'muted speaker'),
                ('🔈', 'speaker low'),
                ('🔉', 'speaker medium'),
                ('🔊', 'speaker high loud'),
                ('🔔', 'bell notification'),
                ('🔕', 'bell slash'),
                ('🔴', 'red circle'),
                ('🟠', 'orange circle'),
                ('🟡', 'yellow circle'),
                ('🟢', 'green circle'),
                ('🔵', 'blue circle'),
                ('🟣', 'purple circle'),
                ('🟤', 'brown circle'),
                ('⚫', 'black circle'),
                ('⚪', 'white circle'),
                ('🟥', 'red square'),
                ('🟧', 'orange square'),
                ('🟨', 'yellow square'),
                ('🟩', 'green square'),
                ('🟦', 'blue square'),
                ('🟪', 'purple square'),
                ('🟫', 'brown square'),
                ('⬛', 'black large square'),
                ('⬜', 'white large square'),
                # Arrows
                ('⬆️', 'up arrow'),
                ('↗️', 'up right arrow'),
                ('➡️', 'right arrow'),
                ('↘️', 'down right arrow'),
                ('⬇️', 'down arrow'),
                ('↙️', 'down left arrow'),
                ('⬅️', 'left arrow'),
                ('↖️', 'up left arrow'),
                ('↕️', 'up down arrow'),
                ('↔️', 'left right arrow'),
                ('🔄', 'counterclockwise arrows refresh'),
                ('🔃', 'clockwise arrows'),
                ('🔀', 'shuffle'),
                ('🔁', 'repeat'),
                ('🔂', 'repeat single'),
                ('▶️', 'play button'),
                ('⏸️', 'pause button'),
                ('⏹️', 'stop button'),
                ('⏺️', 'record button'),
                ('⏭️', 'next track button'),
                ('⏮️', 'last track button'),
                ('⏩', 'fast forward'),
                ('⏪', 'rewind'),
                # Zodiac
                ('♈', 'aries'),
                ('♉', 'taurus'),
                ('♊', 'gemini'),
                ('♋', 'cancer'),
                ('♌', 'leo'),
                ('♍', 'virgo'),
                ('♎', 'libra'),
                ('♏', 'scorpio'),
                ('♐', 'sagittarius'),
                ('♑', 'capricorn'),
                ('♒', 'aquarius'),
                ('♓', 'pisces'),
                # Other symbols
                ('⚛️', 'atom symbol'),
                ('☮️', 'peace symbol'),
                ('☯️', 'yin yang'),
                ('✝️', 'cross'),
                ('☪️', 'star crescent'),
                ('🕉️', 'om'),
                ('☸️', 'wheel dharma'),
                ('✡️', 'star david'),
                ('🔯', 'six pointed star'),
                ('🛐', 'place worship'),
                ('⚕️', 'medical symbol'),
                ('♻️', 'recycling symbol'),
                ('⚜️', 'fleur de lis'),
                ('🔱', 'trident emblem'),
                ('📛', 'name badge'),
                ('🔰', 'japanese beginner'),
                ('⭕', 'hollow red circle'),
                ('✳️', 'eight spoked asterisk'),
                ('❇️', 'sparkle'),
                ('🔆', 'bright button'),
                ('🔅', 'dim button'),
                ('〽️', 'part alternation mark'),
                ('©️', 'copyright'),
                ('®️', 'registered'),
                ('™️', 'trade mark'),
                ('#️⃣', 'keycap hash'),
                ('*️⃣', 'keycap asterisk'),
                ('0️⃣', 'keycap zero'),
                ('1️⃣', 'keycap one'),
                ('2️⃣', 'keycap two'),
                ('3️⃣', 'keycap three'),
                ('4️⃣', 'keycap four'),
                ('5️⃣', 'keycap five'),
                ('6️⃣', 'keycap six'),
                ('7️⃣', 'keycap seven'),
                ('8️⃣', 'keycap eight'),
                ('9️⃣', 'keycap nine'),
                ('🔟', 'keycap ten'),
                ('🔠', 'input latin uppercase'),
                ('🔡', 'input latin lowercase'),
                ('🔢', 'input numbers'),
                ('🔣', 'input symbols'),
                ('🔤', 'input latin letters'),
                ('🆎', 'ab button blood type'),
                ('🆑', 'cl button'),
                ('🆒', 'cool button'),
                ('🆓', 'free button'),
                ('🆔', 'id button'),
                ('🆕', 'new button'),
                ('🆖', 'ng button'),
                ('🆗', 'ok button'),
                ('🆘', 'sos button'),
                ('🆙', 'up button'),
                ('🆚', 'vs button'),
                ('🏳️', 'white flag'),
                ('🏴', 'black flag'),
                ('🚩', 'triangular flag'),
                ('🏁', 'chequered flag finish'),
            ],
        }

        # Build database and search index from curated data
        database = {cat[0]: [] for cat in EMOJI_CATEGORIES}
        search_index = {}

        for category, emoji_list in EMOJI_DATA.items():
            for emoji_char, search_terms in emoji_list:
                database[category].append(emoji_char)

                # Build search index from terms
                for term in search_terms.split():
                    if term not in search_index:
                        search_index[term] = set()
                    search_index[term].add(emoji_char)

        # Cache the results
        self._emoji_database_cache = database
        self._emoji_search_index_cache = search_index
        self._emoji_categories_cache = EMOJI_CATEGORIES

        return database, search_index, EMOJI_CATEGORIES

    def get_date_format(self):
        """Get the current date format string for strftime"""
        format_name = self.settings.get('date_format', 'MM/DD/YYYY')
        return self.DATE_FORMATS.get(format_name, '%m/%d/%Y')

    def get_time_format(self):
        """Get the current time format string for strftime"""
        format_name = self.settings.get('time_format', '12-hour (3:30 PM)')
        return self.TIME_FORMATS.get(format_name, '%I:%M %p')

    def show_settings(self):
        """Show the settings dialog (settings auto-apply when changed)"""
        dialog = SettingsDialog(self, self.settings)
        dialog.exec_()
        # Settings are auto-applied, just reload in case dialog was closed unexpectedly
        self.settings = self.load_settings()

    def get_folders(self):
        """Get list of unique folder names from snippets and custom folders"""
        folders = set()
        # Add folders from snippets
        for snippet in self.snippets:
            folder = snippet.get('folder', 'General')
            if folder:
                folders.add(folder)
        # Add custom folders (including empty ones)
        for folder in self.custom_folders:
            folders.add(folder)
        # Always include "General" and sort alphabetically with General first
        folders.add('General')
        sorted_folders = sorted(folders, key=lambda x: (x != 'General', x.lower()))
        return sorted_folders
    
    def refresh_tree(self):
        """Refresh the snippets tree with folder grouping"""
        self.tree.clear()

        # Group snippets by folder
        folder_snippets = {}
        for i, snippet in enumerate(self.snippets):
            folder = snippet.get('folder', 'General')
            if not folder:
                folder = 'General'
            if folder not in folder_snippets:
                folder_snippets[folder] = []
            folder_snippets[folder].append((i, snippet))

        # Include empty custom folders
        for folder in self.custom_folders:
            if folder not in folder_snippets:
                folder_snippets[folder] = []

        # Always include General
        if 'General' not in folder_snippets:
            folder_snippets['General'] = []

        # Sort folders (General first, then alphabetically)
        sorted_folders = sorted(folder_snippets.keys(), key=lambda x: (x != 'General', x.lower()))

        # Create tree items
        for folder in sorted_folders:
            # Create folder item
            folder_item = QTreeWidgetItem(self.tree)
            snippet_count = len(folder_snippets[folder])
            # Start expanded with down arrow
            folder_item.setText(0, f"▼  {folder} ({snippet_count})")
            folder_item.setData(0, Qt.UserRole, {'type': 'folder', 'name': folder, 'count': snippet_count})
            folder_item.setExpanded(True)

            # Style folder row
            folder_font = folder_item.font(0)
            folder_font.setBold(True)
            folder_item.setFont(0, folder_font)
            folder_item.setForeground(0, QColor('#FF6B00'))
            # Set folder background based on current theme
            if hasattr(self, 'current_theme') and self.current_theme == 'Light':
                folder_item.setBackground(0, QColor(230, 230, 230))
                folder_item.setBackground(1, QColor(230, 230, 230))
                folder_item.setBackground(2, QColor(230, 230, 230))
            else:
                folder_item.setBackground(0, QColor(30, 30, 30))
                folder_item.setBackground(1, QColor(30, 30, 30))
                folder_item.setBackground(2, QColor(30, 30, 30))

            # Add snippet children
            for snippet_index, snippet in folder_snippets[folder]:
                snippet_item = QTreeWidgetItem(folder_item)
                snippet_item.setText(0, snippet.get('trigger', ''))
                snippet_item.setText(1, snippet.get('description', ''))
                type_name = {
                    'simple': 'Simple',
                    'variables': 'Variables',
                    'form': 'Form',
                    'text_image': 'Text+Image',
                    'universal': 'Universal'
                }.get(snippet.get('type', 'universal'), 'Universal')
                snippet_item.setText(2, type_name)
                # Store the snippet index for retrieval
                snippet_item.setData(0, Qt.UserRole, {'type': 'snippet', 'index': snippet_index})

    def refresh_table(self):
        """Alias for refresh_tree for backward compatibility"""
        self.refresh_tree()

    def update_status_indicator(self, active):
        """Update the status indicator appearance"""
        if active:
            self.status_indicator.setText("\u2022 Active")
            self.status_indicator.setStyleSheet("""
                QLabel {
                    color: #4CAF50;
                    font-weight: 500;
                    font-size: 11px;
                }
            """)
        else:
            self.status_indicator.setText("\u2022 Inactive")
            self.status_indicator.setStyleSheet("""
                QLabel {
                    color: #F44336;
                    font-weight: 500;
                    font-size: 11px;
                }
            """)

    def add_snippet(self):
        """Add a new snippet - switch to editor view"""
        self.editor_widget.set_folders(self.get_folders())
        self.editor_widget.set_snippets(self.snippets)
        # Pre-select the currently selected folder
        selected_folder = self.get_selected_folder()
        self.editor_widget.load_snippet(None, -1, selected_folder)
        self.stacked_widget.setCurrentIndex(1)

    def get_selected_folder(self):
        """Get the folder name from the currently selected tree item"""
        current_item = self.tree.currentItem()
        if current_item:
            data = current_item.data(0, Qt.UserRole)
            if data:
                if data.get('type') == 'folder':
                    return data.get('name', 'General')
                elif data.get('type') == 'snippet':
                    # Get parent folder
                    parent = current_item.parent()
                    if parent:
                        parent_data = parent.data(0, Qt.UserRole)
                        if parent_data and parent_data.get('type') == 'folder':
                            return parent_data.get('name', 'General')
        return 'General'

    def edit_snippet(self):
        """Edit selected snippet - switch to editor view"""
        snippet_index = self.get_selected_snippet_index()
        if snippet_index >= 0:
            self.editor_widget.set_folders(self.get_folders())
            self.editor_widget.set_snippets(self.snippets)
            self.editor_widget.load_snippet(self.snippets[snippet_index], snippet_index)
            self.stacked_widget.setCurrentIndex(1)

    def get_selected_snippet_index(self):
        """Get the snippet index from the currently selected tree item"""
        current_item = self.tree.currentItem()
        if current_item:
            data = current_item.data(0, Qt.UserRole)
            if data and data.get('type') == 'snippet':
                return data.get('index', -1)
        return -1

    def on_tree_click(self, index):
        """Handle single click on tree item - toggle folder expansion"""
        current_item = self.tree.currentItem()
        if current_item:
            data = current_item.data(0, Qt.UserRole)
            if data and data.get('type') == 'folder':
                # Toggle expansion state
                current_item.setExpanded(not current_item.isExpanded())

    def on_folder_expanded(self, item):
        """Update folder arrow when expanded"""
        data = item.data(0, Qt.UserRole)
        if data and data.get('type') == 'folder':
            folder_name = data.get('name', '')
            count = data.get('count', 0)
            item.setText(0, f"▼  {folder_name} ({count})")

    def on_folder_collapsed(self, item):
        """Update folder arrow when collapsed"""
        data = item.data(0, Qt.UserRole)
        if data and data.get('type') == 'folder':
            folder_name = data.get('name', '')
            count = data.get('count', 0)
            item.setText(0, f"▶  {folder_name} ({count})")

    def on_tree_double_click(self, index):
        """Handle double-click on tree item"""
        current_item = self.tree.currentItem()
        if current_item:
            data = current_item.data(0, Qt.UserRole)
            if data and data.get('type') == 'snippet':
                self.edit_snippet()

    def on_editor_save(self, snippet):
        """Handle save from editor widget"""
        try:
            if self.editor_widget.is_editing:
                # Update existing snippet
                self.snippets[self.editor_widget.edit_index] = snippet
            else:
                # Add new snippet
                self.snippets.append(snippet)
                # Update editor to editing mode so subsequent saves update the same snippet
                self.editor_widget.is_editing = True
                self.editor_widget.edit_index = len(self.snippets) - 1
                self.editor_widget.title_label.setText("Edit Snippet")
            self.save_snippets()
            self.refresh_tree()
            # Show "Saved" notification instead of going back
            self.show_saved_notification()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save snippet: {str(e)}")

    def show_saved_notification(self):
        """Show a brief 'Saved!' notification on the editor"""
        # Create a notification label if it doesn't exist
        if not hasattr(self, 'saved_notification'):
            self.saved_notification = QLabel("✓ Saved!", self)
            self.saved_notification.setStyleSheet("""
                QLabel {
                    background-color: rgba(76, 175, 80, 220);
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 14px;
                }
            """)
            self.saved_notification.setAlignment(Qt.AlignCenter)
            self.saved_notification.hide()

        # Position the notification at the top center
        self.saved_notification.adjustSize()
        x = (self.width() - self.saved_notification.width()) // 2
        self.saved_notification.move(x, 60)
        self.saved_notification.show()
        self.saved_notification.raise_()

        # Hide after 2 seconds
        QTimer.singleShot(2000, self.saved_notification.hide)

    def on_editor_cancel(self):
        """Handle cancel from editor widget"""
        self.stacked_widget.setCurrentIndex(0)

    def delete_snippet(self):
        """Delete selected snippet or folder"""
        # Check if a tree item is selected
        selected_items = self.tree.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        # Handle folder deletion
        if data.get('type') == 'folder':
            folder_name = data.get('name', '')
            if folder_name:
                self.delete_folder(folder_name)
            return

        # Handle snippet deletion
        snippet_index = self.get_selected_snippet_index()
        if snippet_index >= 0:
            reply = QMessageBox.question(self, 'Delete Snippet',
                                        'Are you sure you want to delete this snippet?',
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                del self.snippets[snippet_index]
                self.save_snippets()
                self.refresh_tree()

    def add_folder(self):
        """Add a new folder"""
        name, ok = QInputDialog.getText(self, 'New Folder', 'Enter folder name:')
        if ok and name:
            name = name.strip()
            if name:
                # Check if folder already exists
                existing_folders = self.get_folders()
                if name in existing_folders:
                    QMessageBox.warning(self, 'Folder Exists', f'A folder named "{name}" already exists.')
                    return
                # Add to custom folders and save
                self.custom_folders.append(name)
                self.save_folders()
                self.refresh_tree()

    def show_tree_context_menu(self, position):
        """Show context menu for tree items"""
        item = self.tree.itemAt(position)
        if not item:
            return

        data = item.data(0, Qt.UserRole)
        if not data:
            return

        menu = QMenu(self)

        if data.get('type') == 'folder':
            folder_name = data.get('name', '')
            rename_action = QAction(f'Rename "{folder_name}"', self)
            rename_action.triggered.connect(lambda checked, fn=folder_name: self.rename_folder(fn))
            menu.addAction(rename_action)

            if folder_name != 'General':  # Can't delete General folder
                delete_action = QAction(f'Delete "{folder_name}"', self)
                delete_action.triggered.connect(lambda checked, fn=folder_name: self.delete_folder(fn))
                menu.addAction(delete_action)

        elif data.get('type') == 'snippet':
            edit_action = QAction('Edit Snippet', self)
            edit_action.triggered.connect(self.edit_snippet)
            menu.addAction(edit_action)

            delete_action = QAction('Delete Snippet', self)
            delete_action.triggered.connect(self.delete_snippet)
            menu.addAction(delete_action)

        if menu.actions():
            menu.exec_(self.tree.viewport().mapToGlobal(position))

    def rename_folder(self, old_name):
        """Rename a folder"""
        new_name, ok = QInputDialog.getText(self, 'Rename Folder',
                                            f'Enter new name for "{old_name}":',
                                            QLineEdit.Normal, old_name)
        if ok and new_name:
            new_name = new_name.strip()
            if not new_name:
                return
            if new_name == old_name:
                return

            # Check if new name already exists
            existing_folders = self.get_folders()
            if new_name in existing_folders:
                QMessageBox.warning(self, 'Folder Exists', f'A folder named "{new_name}" already exists.')
                return

            # Update all snippets in this folder
            for snippet in self.snippets:
                if snippet.get('folder', 'General') == old_name:
                    snippet['folder'] = new_name

            # Update custom folders if present
            if old_name in self.custom_folders:
                self.custom_folders.remove(old_name)
                self.custom_folders.append(new_name)
                self.save_folders()

            self.save_snippets()
            self.refresh_tree()

    def delete_folder(self, folder_name):
        """Delete a folder (moves snippets to General)"""
        if folder_name == 'General':
            QMessageBox.warning(self, 'Cannot Delete', 'The General folder cannot be deleted.')
            return

        # Count snippets in folder
        count = sum(1 for s in self.snippets if s.get('folder', 'General') == folder_name)

        if count > 0:
            reply = QMessageBox.question(self, 'Delete Folder',
                                        f'Delete folder "{folder_name}"?\n\n'
                                        f'{count} snippet(s) will be moved to General.',
                                        QMessageBox.Yes | QMessageBox.No)
        else:
            reply = QMessageBox.question(self, 'Delete Folder',
                                        f'Delete folder "{folder_name}"?',
                                        QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            # Move all snippets to General
            for snippet in self.snippets:
                if snippet.get('folder', 'General') == folder_name:
                    snippet['folder'] = 'General'

            # Remove from custom folders if present
            if folder_name in self.custom_folders:
                self.custom_folders.remove(folder_name)
                self.save_folders()

            self.save_snippets()
            self.refresh_tree()
    
    def handle_trigger(self, snippet):
        """Handle triggered snippet - called from listener thread"""
        # Delete the trigger text and expand
        QTimer.singleShot(50, lambda: self.delete_trigger_and_expand(snippet))
    
    def delete_trigger_and_expand(self, snippet):
        """Delete trigger and expand content"""
        try:
            trigger = snippet.get('trigger', '')
            content = snippet.get('content', '')
            rich_html = snippet.get('rich_html')
            snippet_type = snippet.get('type', 'universal')

            print(f"Expanding snippet type: {snippet_type}")

            # Delete the trigger text using ydotool (keycode 14 = backspace)
            for _ in range(len(trigger)):
                ydotool_key(14)
                time.sleep(0.01)

            # If snippet has rich HTML content (copied from word processor), paste it directly
            if rich_html:
                print("Snippet has rich HTML content, pasting directly")
                self.paste_html(rich_html)
                print("Snippet expansion complete (rich HTML)")
                return

            # Check if content has bullet or numbered lists - convert to HTML for proper list behavior
            def convert_lists_to_html(text):
                """Convert plain text bullet/number lists to HTML lists"""
                lines = text.split('\n')
                result = []
                in_bullet_list = False
                in_numbered_list = False

                for line in lines:
                    stripped = line.strip()

                    # Check for bullet point (• or - or *)
                    if stripped.startswith('• ') or stripped.startswith('- ') or stripped.startswith('* '):
                        item_text = stripped[2:]
                        if not in_bullet_list:
                            if in_numbered_list:
                                result.append('</ol>')
                                in_numbered_list = False
                            result.append('<ul>')
                            in_bullet_list = True
                        result.append(f'<li>{item_text}</li>')

                    # Check for numbered list (1. 2. 3. etc.)
                    elif re.match(r'^\d+\.\s', stripped):
                        item_text = re.sub(r'^\d+\.\s*', '', stripped)
                        if not in_numbered_list:
                            if in_bullet_list:
                                result.append('</ul>')
                                in_bullet_list = False
                            result.append('<ol>')
                            in_numbered_list = True
                        result.append(f'<li>{item_text}</li>')

                    else:
                        # Regular line - close any open lists
                        if in_bullet_list:
                            result.append('</ul>')
                            in_bullet_list = False
                        if in_numbered_list:
                            result.append('</ol>')
                            in_numbered_list = False
                        if stripped:
                            result.append(f'<p>{line}</p>')
                        elif line == '':
                            result.append('<br>')

                # Close any remaining open lists
                if in_bullet_list:
                    result.append('</ul>')
                if in_numbered_list:
                    result.append('</ol>')

                return ''.join(result)

            def convert_formatting_to_html(text):
                """Convert markdown-style formatting to HTML"""
                # Convert bold: **text** -> <b>text</b>
                text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
                # Convert italic: *text* -> <i>text</i> (but not inside bold tags)
                text = re.sub(r'(?<![*<])\*([^*]+?)\*(?![*>])', r'<i>\1</i>', text)
                # <u>text</u> is already HTML, no conversion needed
                # Convert newlines to <br> for proper line breaks
                text = text.replace('\n', '<br>')
                return text

            def has_formatting_markers(text):
                """Check if text has bold, italic, or underline markers"""
                has_bold = bool(re.search(r'\*\*.+?\*\*', text))
                has_italic = bool(re.search(r'(?<![*])\*[^*]+?\*(?![*])', text))
                has_underline = bool(re.search(r'<u>.+?</u>', text, re.IGNORECASE))
                return has_bold or has_italic or has_underline

            # Check if content has form fields (user input needed) - DO THIS FIRST
            # Form fields: {{name}}, {{name=opts}}, {{name:toggle}}, {{name:multi=opts}}, {{snippet:trigger}}
            # Special variables (no input): {{date}}, {{date+N}}, {{date-N}}, {{time}}, {{datetime}}, {{clipboard}}, {{cursor}}, {{image:path}}, {{calc:expr}}
            special_vars_only = r'^(date([+-]\d+)?|time|datetime|clipboard|cursor|image|table|calc)$'
            has_any_vars = bool(re.search(r'\{\{[^}]+\}\}', content))

            # Check if there are form fields that require user input
            has_form_fields = False
            if has_any_vars:
                # Find all variable names
                all_vars = re.findall(r'\{\{([^}=:]+)(?:[=:]([^}]*))?\}\}', content)
                for var_name, _ in all_vars:
                    var_name = var_name.strip()
                    if not re.match(special_vars_only, var_name):
                        has_form_fields = True
                        break
                # Also check for snippet: pattern
                if re.search(r'\{\{snippet:[^}]+\}\}', content):
                    has_form_fields = True

            # Show form popup if there are form fields
            if has_form_fields:
                # Save mouse position before showing dialog (user was typing in target app)
                from PyQt5.QtGui import QCursor
                saved_mouse_pos = QCursor.pos()

                # Use parent=None so the main window doesn't pop up with the dialog
                dialog = SnippetFormDialog(snippet, self.snippets, self.get_date_format(), self.get_time_format(), None)
                dialog.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
                dialog.setAttribute(Qt.WA_ShowWithoutActivating, False)
                # Ensure dialog appears on top and gets focus
                dialog.show()
                dialog.activateWindow()
                dialog.raise_()
                if dialog.exec_() == QDialog.Accepted:
                    content = dialog.get_result()
                    if content is None:
                        return

                    # Ensure SnipForge main window is hidden
                    self.hide()

                    # Move mouse back to original position and click to restore focus
                    time.sleep(0.1)
                    run_ydotool('mousemove', '--absolute', '-x', str(saved_mouse_pos.x()), '-y', str(saved_mouse_pos.y()))
                    time.sleep(0.05)
                    run_ydotool('click', '0xC1')  # Left click
                    time.sleep(0.15)
                else:
                    print("Form dialog cancelled")
                    return

            # Process simple variables (date, time, clipboard)
            has_simple_vars = bool(re.search(r'\{\{(date|time|datetime|clipboard)([+-]\d+)?\}\}', content))
            if has_simple_vars:
                content = self.process_variables(content)

            # Check if content has lists that should be converted to HTML
            has_bullet_list = bool(re.search(r'^[\s]*(•|-|\*)\s', content, re.MULTILINE))
            has_numbered_list = bool(re.search(r'^[\s]*\d+\.\s', content, re.MULTILINE))

            if has_bullet_list or has_numbered_list:
                print("Content has lists, converting to HTML for proper list behavior")
                html_content = convert_lists_to_html(content)
                # Also convert any formatting markers in the list content
                html_content = convert_formatting_to_html(html_content)
                self.paste_html(html_content)
                print("Snippet expansion complete (converted lists)")
                return

            # Check if content has formatting (bold, italic, underline)
            if has_formatting_markers(content):
                print("Content has formatting markers, converting to HTML")
                html_content = convert_formatting_to_html(content)
                self.paste_html(html_content)
                print("Snippet expansion complete (formatted text)")
                return

            # Handle {{cursor}} marker, inline images, tables, and HTML tables
            cursor_marker = '{{cursor}}'
            cursor_pos = content.find(cursor_marker)
            image_pattern = r'\{\{image:([^}]+)\}\}'
            table_marker_pattern = r'\{\{table:(\d+):(\d+)\}\}'
            html_table_pattern = r'<table[^>]*>.*?</table>'
            # Combined pattern to find images, table markers, and HTML tables
            combined_pattern = r'\{\{(image):([^}]+)\}\}|\{\{(table):(\d+):(\d+)\}\}|(<table[^>]*>.*?</table>)'

            def type_content_with_embeds(text):
                """Type text content with inline images and tables. Returns arrow key count."""
                matches = list(re.finditer(combined_pattern, text, re.DOTALL | re.IGNORECASE))
                arrow_count = 0

                if matches:
                    last_end = 0
                    for match in matches:
                        # Type text before this embed
                        text_before = text[last_end:match.start()]
                        if text_before:
                            self.type_text(text_before)
                            arrow_count += len(text_before)
                            time.sleep(0.2)

                        # Check what type of embed this is
                        if match.group(1) == 'image':
                            # Image embed: {{image:path}}
                            image_path = match.group(2)
                            print(f"Pasting inline image: {image_path}")
                            self.paste_image(image_path)
                            arrow_count += 1
                        elif match.group(3) == 'table':
                            # Table marker: {{table:cols:rows}}
                            cols = int(match.group(4))
                            rows = int(match.group(5))
                            print(f"Pasting table marker: {cols}x{rows}")
                            self.paste_table(cols, rows)
                            arrow_count += 1
                        elif match.group(6):
                            # HTML table: <table>...</table>
                            html_content = match.group(6)
                            print(f"Pasting HTML table ({len(html_content)} chars)")
                            self.paste_html(html_content)
                            arrow_count += 1

                        time.sleep(0.2)
                        last_end = match.end()

                    # Type remaining text after last embed
                    text_after = text[last_end:]
                    if text_after:
                        self.type_text(text_after)
                        arrow_count += len(text_after)
                else:
                    # No embeds, just type the text
                    if text:
                        self.type_text(text)
                        arrow_count = len(text)

                return arrow_count

            if cursor_pos != -1:
                # Split at cursor marker
                before_cursor = content[:cursor_pos]
                after_cursor = content[cursor_pos + len(cursor_marker):]

                print(f"Cursor marker found")
                print(f"  before_cursor ({len(before_cursor)} chars): {repr(before_cursor[:50])}")
                print(f"  after_cursor ({len(after_cursor)} chars): {repr(after_cursor[:50])}")

                # Type content before cursor position (including any images)
                type_content_with_embeds(before_cursor)

                # Type content after cursor position (including images inline)
                arrows_after = type_content_with_embeds(after_cursor)

                # Move cursor back to the {{cursor}} position
                if arrows_after > 0:
                    print(f"Moving cursor back {arrows_after} positions")
                    time.sleep(0.1)
                    for _ in range(arrows_after):
                        ydotool_key(105)  # Left arrow key
                        time.sleep(0.02)
            else:
                # No cursor marker, check for embeds (images/tables)
                embed_matches = list(re.finditer(combined_pattern, content, re.DOTALL | re.IGNORECASE))
                if embed_matches:
                    print(f"Found {len(embed_matches)} inline embed(s)")
                    type_content_with_embeds(content)
                else:
                    # No cursor marker, no embeds - just type normally
                    print(f"Typing text content ({len(content)} chars)")
                    self.type_text(content)

            # Handle legacy image_path if present (for backwards compatibility)
            has_inline_images = bool(re.search(image_pattern, content))
            if snippet.get('image_path') and not has_inline_images:
                time.sleep(0.1)
                self.paste_image(snippet.get('image_path'))

            print("Snippet expansion complete")

        except Exception as e:
            print(f"Error expanding snippet: {e}")
    
    def process_variables(self, content):
        """Process variable replacements"""
        from datetime import timedelta

        date_fmt = self.get_date_format()

        # Date arithmetic: {{date+N}} or {{date-N}}
        date_arith_pattern = r'\{\{date([+-])(\d+)\}\}'
        for match in re.finditer(date_arith_pattern, content):
            operator = match.group(1)
            days = int(match.group(2))
            if operator == '-':
                days = -days
            result_date = datetime.now() + timedelta(days=days)
            content = content.replace(match.group(0), result_date.strftime(date_fmt), 1)

        # Basic date and time variables
        time_fmt = self.get_time_format()
        content = content.replace('{{date}}', datetime.now().strftime(date_fmt))
        content = content.replace('{{time}}', datetime.now().strftime(time_fmt))
        content = content.replace('{{datetime}}', datetime.now().strftime(date_fmt + ' ' + time_fmt))

        # Clipboard (supports both text and images)
        if '{{clipboard}}' in content:
            try:
                import tempfile

                if IS_LINUX:
                    # Linux/Wayland: Use wl-paste to check for images
                    try:
                        result = subprocess.run(['wl-paste', '--list-types'],
                                               capture_output=True, text=True, timeout=2)
                        clipboard_types = result.stdout.strip().split('\n') if result.stdout else []

                        # Check if clipboard has an image
                        image_type = None
                        for mime in clipboard_types:
                            if mime in ['image/png', 'image/jpeg', 'image/jpg', 'image/gif']:
                                image_type = mime
                                break

                        if image_type:
                            # Clipboard contains an image - save to temp file
                            ext = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/gif': '.gif'}[image_type]
                            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                            temp_path = temp_file.name
                            temp_file.close()

                            # Save clipboard image to temp file
                            with open(temp_path, 'wb') as f:
                                img_result = subprocess.run(['wl-paste', '--type', image_type],
                                                           capture_output=True, timeout=5)
                                f.write(img_result.stdout)

                            # Replace {{clipboard}} with {{image:temppath}} for inline image handling
                            content = content.replace('{{clipboard}}', f'{{{{image:{temp_path}}}}}')
                        else:
                            # Clipboard contains text
                            clipboard_content = pyperclip.paste()
                            content = content.replace('{{clipboard}}', clipboard_content)
                    except FileNotFoundError:
                        # wl-paste not available, fall back to text
                        clipboard_content = pyperclip.paste()
                        content = content.replace('{{clipboard}}', clipboard_content)

                elif IS_WINDOWS:
                    # Windows: Check for image using PIL
                    try:
                        from PIL import ImageGrab
                        img = ImageGrab.grabclipboard()
                        if img is not None:
                            # Clipboard has an image - save to temp file
                            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                            temp_path = temp_file.name
                            temp_file.close()
                            img.save(temp_path, 'PNG')
                            content = content.replace('{{clipboard}}', f'{{{{image:{temp_path}}}}}')
                        else:
                            # Text content
                            clipboard_content = pyperclip.paste()
                            content = content.replace('{{clipboard}}', clipboard_content)
                    except Exception:
                        clipboard_content = pyperclip.paste()
                        content = content.replace('{{clipboard}}', clipboard_content)
                else:
                    # Other platforms: text only
                    clipboard_content = pyperclip.paste()
                    content = content.replace('{{clipboard}}', clipboard_content)

            except Exception:
                # Fallback to text-only
                try:
                    clipboard_content = pyperclip.paste()
                    content = content.replace('{{clipboard}}', clipboard_content)
                except Exception:
                    content = content.replace('{{clipboard}}', '')

        return content

    def process_calculations(self, content, field_values):
        """Process calculation expressions: {{calc:expression}}"""
        import math

        calc_pattern = r'\{\{calc:([^}]+)\}\}'
        matches = re.findall(calc_pattern, content)

        for expr in matches:
            original_expr = expr
            try:
                # Replace field references with their values
                for field_name, value in field_values.items():
                    # Try to convert to number, otherwise use 0
                    try:
                        num_value = float(value) if value else 0
                    except (ValueError, TypeError):
                        num_value = 0
                    # Replace field name with its numeric value (word boundary matching)
                    expr = re.sub(r'\b' + re.escape(field_name) + r'\b', str(num_value), expr)

                # Define safe math functions
                safe_funcs = {
                    'round': round,
                    'floor': math.floor,
                    'ceil': math.ceil,
                    'abs': abs,
                    'min': min,
                    'max': max,
                    'pow': pow,
                    'sqrt': math.sqrt,
                }

                # Evaluate the expression safely
                # Only allow numbers, operators, parentheses, and safe functions
                allowed_chars = set('0123456789.+-*/%(). ,')
                allowed_names = set(safe_funcs.keys())

                # Check for any remaining words (field names that weren't matched)
                remaining_words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', expr)
                for word in remaining_words:
                    if word not in allowed_names:
                        # Unknown variable - replace with 0
                        expr = re.sub(r'\b' + re.escape(word) + r'\b', '0', expr)

                # Evaluate
                result = eval(expr, {"__builtins__": {}}, safe_funcs)

                # Format result (remove trailing zeros for whole numbers)
                if isinstance(result, float):
                    if result == int(result):
                        result = int(result)
                    else:
                        result = round(result, 2)

                content = content.replace('{{calc:' + original_expr + '}}', str(result), 1)

            except Exception as e:
                # If evaluation fails, replace with error indicator
                print(f"Calculation error: {e} for expression: {expr}")
                content = content.replace('{{calc:' + original_expr + '}}', '[calc error]', 1)

        return content

    def process_form(self, content):
        """Process form inputs"""
        # Track field values for calculations
        field_values = {}

        # Process nested snippets: {{snippet:trigger}}
        snippet_pattern = r'\{\{snippet:([^}]+)\}\}'
        snippet_matches = re.findall(snippet_pattern, content)
        for trigger in snippet_matches:
            trigger = trigger.strip()
            # Find the snippet with this trigger
            nested_content = ''
            for s in self.snippets:
                if s.get('trigger', '') == trigger:
                    nested_content = s.get('content', '')
                    break
            content = content.replace('{{snippet:' + trigger + '}}', nested_content)

        # Recursively process any nested snippets in the expanded content
        if re.search(snippet_pattern, content):
            content = self.process_form(content)
            return content

        # Process toggle sections: {{name:toggle}}content{{/name:toggle}}
        toggle_pattern = r'\{\{([^}:]+):toggle\}\}(.*?)\{\{/\1:toggle\}\}'
        toggle_matches = re.findall(toggle_pattern, content, re.DOTALL)
        for var, inner_content in toggle_matches:
            var = var.strip()
            reply = QMessageBox.question(self, 'Include Section',
                                        f'Include {var}?',
                                        QMessageBox.Yes | QMessageBox.No,
                                        QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                # Keep the inner content, remove the toggle tags
                full_match = '{{' + var + ':toggle}}' + inner_content + '{{/' + var + ':toggle}}'
                content = content.replace(full_match, inner_content, 1)
            else:
                # Remove the entire section
                full_match = '{{' + var + ':toggle}}' + inner_content + '{{/' + var + ':toggle}}'
                content = content.replace(full_match, '', 1)

        # Process multi-select fields: {{name:multi=opt1|opt2|opt3}}
        multi_pattern = r'\{\{([^}:]+):multi=([^}]+)\}\}'
        multi_matches = re.findall(multi_pattern, content)
        for var, options in multi_matches:
            var = var.strip()
            option_list = [opt.strip() for opt in options.split('|')]
            selected = self.show_multi_select_dialog(var, option_list)
            field_values[var] = selected
            content = content.replace('{{' + var + ':multi=' + options + '}}', selected)

        # Find all {{variable}} and {{variable=options}} patterns
        pattern = r'\{\{([^}=:]+)(?:=([^}]+))?\}\}'
        matches = re.findall(pattern, content)

        # Get input for each variable in the main thread
        for var, options in matches:
            var = var.strip()

            if var in ['date', 'time', 'datetime', 'clipboard', 'cursor']:
                # Skip special variables, they're handled by process_variables
                continue

            if options:
                # Dropdown menu
                option_list = [opt.strip() for opt in options.split('|')]
                item, ok = QInputDialog.getItem(self, 'Form Input',
                                               f'Select {var}:', option_list, 0, False)
                if ok and item:
                    field_values[var] = item
                    content = content.replace('{{' + var + '=' + options + '}}', item)
                else:
                    field_values[var] = ''
                    content = content.replace('{{' + var + '=' + options + '}}', '')
            else:
                # Text input
                text, ok = QInputDialog.getText(self, 'Form Input', f'Enter {var}:')
                if ok and text:
                    field_values[var] = text
                    content = content.replace('{{' + var + '}}', text)
                else:
                    field_values[var] = ''
                    content = content.replace('{{' + var + '}}', '')

        # Process calculations: {{calc:expression}}
        content = self.process_calculations(content, field_values)

        # Process remaining variables (date, time, etc.)
        content = self.process_variables(content)

        return content

    def show_multi_select_dialog(self, field_name, options):
        """Show a dialog with checkboxes for multiple selection"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f'Select {field_name}')
        dialog.setMinimumWidth(300)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #121212;
            }
            QCheckBox {
                color: #E0E0E0;
                spacing: 8px;
                padding: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #424242;
                border-radius: 4px;
                background-color: #1E1E1E;
            }
            QCheckBox::indicator:checked {
                background-color: #FF6B00;
                border-color: #FF6B00;
            }
            QCheckBox::indicator:hover {
                border-color: #FF6B00;
            }
        """)

        layout = QVBoxLayout(dialog)

        label = QLabel(f"Select {field_name}:")
        label.setStyleSheet("color: #E0E0E0; font-weight: bold; padding: 8px;")
        layout.addWidget(label)

        checkboxes = []
        for option in options:
            cb = QCheckBox(option)
            checkboxes.append(cb)
            layout.addWidget(cb)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        button_box.setStyleSheet("""
            QPushButton {
                background-color: #FF6B00;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #FF8C00;
            }
        """)
        layout.addWidget(button_box)

        if dialog.exec_() == QDialog.Accepted:
            selected = [cb.text() for cb in checkboxes if cb.isChecked()]
            return ', '.join(selected)
        return ''
    
    def paste_image(self, image_path):
        """Copy image to clipboard and paste it"""
        try:
            # Verify the image file exists
            if not Path(image_path).exists():
                print(f"Image file not found: {image_path}")
                return

            print(f"Pasting image: {image_path}")

            if IS_LINUX:
                # Linux/Wayland: Use wl-copy
                # Determine image MIME type
                if image_path.lower().endswith('.png'):
                    mime_type = 'image/png'
                elif image_path.lower().endswith(('.jpg', '.jpeg')):
                    mime_type = 'image/jpeg'
                elif image_path.lower().endswith('.gif'):
                    mime_type = 'image/gif'
                else:
                    mime_type = 'image/png'

                try:
                    # wl-copy must stay running to serve clipboard requests on Wayland
                    # Use Popen to run it in background
                    with open(image_path, 'rb') as f:
                        self._wl_copy_proc = subprocess.Popen(
                            ['wl-copy', '--type', mime_type],
                            stdin=f,
                            env=os.environ.copy(),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )

                    print("wl-copy started (background)")
                    time.sleep(0.4)

                except Exception as e:
                    print(f"wl-copy error: {e}")
                    import traceback
                    traceback.print_exc()
                    return

                # Paste using Ctrl+V
                print("Pasting image with Ctrl+V...")
                press_ctrl_v()

            elif IS_WINDOWS:
                # Windows: Copy image to clipboard using PIL
                try:
                    from PIL import Image as PILImage
                    img = PILImage.open(image_path)

                    # Convert to BMP for Windows clipboard (common format)
                    output = io.BytesIO()
                    img.convert('RGB').save(output, 'BMP')
                    data = output.getvalue()[14:]  # Skip BMP header
                    output.close()

                    # Use win32clipboard
                    import win32clipboard
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
                    win32clipboard.CloseClipboard()

                    time.sleep(0.2)

                    # Paste using Ctrl+V
                    press_ctrl_v()

                except ImportError:
                    # win32clipboard not available, try pyautogui
                    print("win32clipboard not available, trying pyautogui...")
                    try:
                        import pyautogui
                        # Set clipboard image via PyQt
                        from PyQt5.QtCore import QMimeData
                        from PyQt5.QtGui import QImage
                        qimg = QImage(image_path)
                        QApplication.clipboard().setImage(qimg)
                        time.sleep(0.2)
                        pyautogui.hotkey('ctrl', 'v')
                    except Exception as e:
                        print(f"Failed to paste image: {e}")
                        return

            # Wait for paste to complete
            time.sleep(0.4)

            if IS_LINUX:
                # Press Escape to deselect the image (apps auto-select pasted images)
                ydotool_key(1)  # Escape key
                time.sleep(0.2)
                # Press End to move cursor to end of line (after image)
                ydotool_key(107)  # End key
                time.sleep(0.1)
            elif IS_WINDOWS:
                # Similar cleanup on Windows
                kb = get_keyboard_controller()
                kb.press(Key.esc)
                kb.release(Key.esc)
                time.sleep(0.2)
                kb.press(Key.end)
                kb.release(Key.end)

            print("Image paste completed")

        except Exception as e:
            print(f"Error pasting image: {e}")
            import traceback
            traceback.print_exc()

    def paste_table(self, cols, rows):
        """Create and paste an HTML table that word processors convert to native tables"""
        try:
            # Build HTML table
            html_lines = ['<table border="1" cellpadding="5" cellspacing="0">']
            for r in range(rows):
                html_lines.append('<tr>')
                for c in range(cols):
                    html_lines.append('<td>&nbsp;</td>')
                html_lines.append('</tr>')
            html_lines.append('</table>')
            html_content = ''.join(html_lines)

            print(f"Pasting {cols}x{rows} table as HTML")
            self.paste_html(html_content)
            print("Table paste completed")

        except Exception as e:
            print(f"Error pasting table: {e}")
            import traceback
            traceback.print_exc()

    def paste_html(self, html_content):
        """Paste HTML content so word processors convert it to native formatting"""
        try:
            print(f"Pasting HTML content")

            if IS_LINUX:
                try:
                    # Use wl-copy with text/html MIME type
                    self._wl_copy_proc = subprocess.Popen(
                        ['wl-copy', '--type', 'text/html'],
                        stdin=subprocess.PIPE,
                        env=os.environ.copy(),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    self._wl_copy_proc.stdin.write(html_content.encode('utf-8'))
                    self._wl_copy_proc.stdin.close()

                    print("HTML copied to clipboard (Linux)")
                    time.sleep(0.4)

                except Exception as e:
                    print(f"wl-copy error: {e}")
                    import traceback
                    traceback.print_exc()
                    return

                # Paste using Ctrl+V
                print("Pasting HTML with Ctrl+V...")
                press_ctrl_v()
                time.sleep(0.4)

                # Cleanup
                ydotool_key(1)  # Escape key
                time.sleep(0.1)
                ydotool_key(107)  # End key
                time.sleep(0.1)

            elif IS_WINDOWS:
                try:
                    # On Windows, use win32clipboard for HTML format
                    import win32clipboard

                    # Windows HTML clipboard format requires specific header
                    html_header = """Version:0.9
StartHTML:00000097
EndHTML:{end_html:08d}
StartFragment:00000133
EndFragment:{end_fragment:08d}
<html><body>
<!--StartFragment-->{html}<!--EndFragment-->
</body></html>"""

                    fragment = html_content
                    html_formatted = html_header.format(
                        html=fragment,
                        end_html=97 + 36 + len(fragment) + 36,
                        end_fragment=133 + len(fragment)
                    )

                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    # CF_HTML = 49429 is the standard Windows HTML clipboard format
                    win32clipboard.SetClipboardData(
                        win32clipboard.RegisterClipboardFormat("HTML Format"),
                        html_formatted.encode('utf-8')
                    )
                    win32clipboard.CloseClipboard()

                    print("HTML copied to clipboard (Windows)")
                    time.sleep(0.2)

                    # Paste using Ctrl+V
                    press_ctrl_v()
                    time.sleep(0.4)

                    # Cleanup
                    kb = get_keyboard_controller()
                    kb.press(Key.esc)
                    kb.release(Key.esc)
                    time.sleep(0.1)
                    kb.press(Key.end)
                    kb.release(Key.end)

                except ImportError:
                    # Fallback: just paste as plain text
                    print("win32clipboard not available, pasting as plain text")
                    pyperclip.copy(html_content)
                    press_ctrl_v()

            print("HTML paste completed")

        except Exception as e:
            print(f"Error pasting HTML: {e}")
            import traceback
            traceback.print_exc()

    def type_text(self, text):
        """Type text using clipboard paste (cross-platform)"""
        # Check if text has formatting markers that need HTML conversion
        has_bold = bool(re.search(r'\*\*.+?\*\*', text))
        has_italic = bool(re.search(r'(?<![*])\*[^*]+?\*(?![*])', text))
        has_underline = bool(re.search(r'<u>.+?</u>', text, re.IGNORECASE))

        if has_bold or has_italic or has_underline:
            # Convert formatting to HTML and paste as rich text
            html_text = text
            # Convert bold: **text** -> <b>text</b>
            html_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html_text)
            # Convert italic: *text* -> <i>text</i>
            html_text = re.sub(r'(?<![*<])\*([^*]+?)\*(?![*>])', r'<i>\1</i>', html_text)
            # Convert newlines to <br>
            html_text = html_text.replace('\n', '<br>')
            self.paste_html(html_text)
            return

        # Use clipboard for faster typing
        try:
            old_clipboard = pyperclip.paste()
            pyperclip.copy(text)
            time.sleep(0.1)  # Wait for clipboard to be ready

            # Paste using Ctrl+V (cross-platform)
            # Note: Ctrl+Shift+V opens "Paste Special" in LibreOffice
            print(f"Sending Ctrl+V to paste {len(text)} chars...")
            press_ctrl_v()

            time.sleep(0.15)
            pyperclip.copy(old_clipboard)
        except:
            # Fallback to typing directly with ydotool
            ydotool_type(text)
    
    def check_show_request(self):
        """Check if another instance is requesting to show the window"""
        request_file = get_config_dir() / 'show_request'
        if request_file.exists():
            try:
                request_file.unlink()
                self.show()
                self.activateWindow()
                self.raise_()
            except:
                pass
    
    def quit_application(self):
        """Quit the application"""
        self.listener_thread.stop()
        self.listener_thread.wait()
        QApplication.quit()


def disable_kde_blur(widget):
    """Disable KDE blur effect on a window (X11 only)"""
    try:
        # Try to use X11 to disable blur
        from PyQt5.QtX11Extras import QX11Info
        if QX11Info.isPlatformX11():
            import ctypes
            try:
                xlib = ctypes.CDLL('libX11.so.6')
                display = QX11Info.display()
                window_id = int(widget.winId())

                # Set _KDE_NET_WM_BLUR_BEHIND_REGION to empty to disable blur
                atom_name = b"_KDE_NET_WM_BLUR_BEHIND_REGION"
                atom = xlib.XInternAtom(display, atom_name, False)
                xlib.XDeleteProperty(display, window_id, atom)
                xlib.XFlush(display)
            except:
                pass
    except ImportError:
        pass


def main():
    # Single instance check (cross-platform)
    lock_handle = None

    if IS_WINDOWS:
        # Windows: Use a named mutex
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            ERROR_ALREADY_EXISTS = 183

            # Create a named mutex
            mutex_name = "SnipForgeSingleInstanceMutex"
            lock_handle = kernel32.CreateMutexW(None, False, mutex_name)

            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                # Another instance is running - request it to show its window
                print("SnipForge is already running. Bringing it to front...")
                request_file = get_config_dir() / 'show_request'
                request_file.parent.mkdir(parents=True, exist_ok=True)
                request_file.touch()
                sys.exit(0)
        except Exception as e:
            print(f"Warning: Could not create mutex: {e}")
    else:
        # Linux/macOS: Use Unix abstract sockets
        try:
            lock_handle = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            lock_file = get_config_dir() / 'snipforge.lock'
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_handle.bind('\0' + str(lock_file))
        except socket.error:
            # Another instance is running - request it to show its window
            print("SnipForge is already running. Bringing it to front...")
            request_file = get_config_dir() / 'show_request'
            request_file.touch()
            sys.exit(0)

    # Disable Qt's automatic handling of system theme transparency
    import os
    os.environ['QT_QUICK_CONTROLS_STYLE'] = 'Default'

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName("snipforge")  # Match StartupWMClass in .desktop file

    # Configure tooltip styling at application level to avoid compositor transparency
    from PyQt5.QtGui import QPalette, QColor
    palette = app.palette()
    palette.setColor(QPalette.ToolTipBase, QColor('#333333'))
    palette.setColor(QPalette.ToolTipText, QColor('#FFFFFF'))
    app.setPalette(palette)

    # Set application-wide tooltip stylesheet
    app.setStyleSheet("""
        QToolTip {
            background-color: #333333;
            color: #FFFFFF;
            border: 1px solid #555555;
            border-radius: 4px;
            padding: 4px 8px;
            opacity: 255;
        }
    """)

    # Install custom tooltip filter for widgets with tooltips
    tooltip_filter = ToolTipFilter()
    app.installEventFilter(tooltip_filter)

    # Set application-wide icon (required for Linux window managers)
    config_dir = get_config_dir()
    app_icon_path = config_dir / 'app_icon.png'
    if not app_icon_path.exists():
        app_icon_path = config_dir / 'app_icon.ico'
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    window = MainWindow()
    # Start minimized to tray - click tray icon to show window
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
