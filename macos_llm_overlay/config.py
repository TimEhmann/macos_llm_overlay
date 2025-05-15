"""
Configuration settings for the macOS LLM Overlay application.
This file centralizes various parameters like URLs, paths, UI dimensions,
and hotkey definitions.
"""
from Quartz import (
    kCGEventFlagMaskShift,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
)
from pathlib import Path

# The website to load in the WebView.
PROVIDER_URLS = {
    "ChatGPT": "https://chat.openai.com",
    "Gemini": "https://gemini.google.com/app",
    "AIStudio": "https://aistudio.google.com",
    "Claude": "https://claude.ai/chats",
    "Grok": "https://grok.com/chat"
}
DEFAULT_PROVIDER_NAME = "AIStudio"
CURRENT_PROVIDER_KEY = "CurrentLLMProvider"

# Filename of the application icon used in the status bar.
# Resolved to an absolute path in app.py.
ICON_PATH = "macos_llm_overlay-icon.png"

# Key used to save and load the window's frame (position and size) in UserDefaults.
FRAME_SAVE_NAME = "OverlayWindowFrame"

# Title for the application, used in menus, etc.
APP_TITLE = "LLM Overlay App"

# Height of the draggable area at the top of the window.
DRAG_AREA_HEIGHT = 20

# Mask for modifier keys relevant to the global hotkey.
# This defines which modifier keys are considered when checking for a hotkey press.
TOGGLE_KEY_MASK = (
    kCGEventFlagMaskShift |
    kCGEventFlagMaskControl |
    kCGEventFlagMaskAlternate |
    kCGEventFlagMaskCommand
)

# Default global hotkey to toggle the window.
# 'flags' are Quartz CGEventFlags (e.g., kCGEventFlagMaskCommand).
# 'key' is the virtual keycode (e.g., 49 for Spacebar).
TOGGLE_KEY = {"flags": kCGEventFlagMaskCommand, "key": 49} # Default to Command + Space

# Initial dimensions for the window if no saved frame is found.
INITIAL_WIDTH = 800
INITIAL_HEIGHT = 600

# Directory for storing application logs, including crash reports.
LOG_DIR = Path.home() / "Library" / "Logs" / "macos-llm-overlay"
LOG_DIR.mkdir(parents=True, exist_ok=True) # Ensure the log directory exists.

# File path for storing the user-customized global hotkey.
TOGGLE_FILE = LOG_DIR / "custom_toggle.json"
