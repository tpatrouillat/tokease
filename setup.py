"""
py2app build configuration for Claude Usage Tracker.

Build the .app bundle:
    python setup.py py2app

Build a dev/test version (symlinked, faster):
    python setup.py py2app -A
"""

from setuptools import setup

APP = ["tracker.py"]
APP_NAME = "Claude Usage Tracker"

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "assets/icon.icns",
    "plist": {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "com.tpatrouillat.claude-usage-tracker",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,  # Menu bar app — no Dock icon
        "NSHumanReadableCopyright": "MIT License — Thibault Patrouillat",
    },
}

setup(
    name=APP_NAME,
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
