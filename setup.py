"""
py2app build configuration for Tokease.

Build the .app bundle:
    python setup.py py2app

Build a dev/test version (symlinked, faster):
    python setup.py py2app -A
"""

from setuptools import setup

APP = ["tracker.py"]
APP_NAME = "Tokease"

# Bundled into Resources/assets/ so tracker.py can find the menu bar icon
# both from source (repo root) and from the frozen .app.
DATA_FILES = [("assets", ["assets/menubar-template.png"])]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "assets/icon.icns",
    "plist": {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "com.tpatrouillat.tokease",
        "CFBundleVersion": "1.0.3",
        "CFBundleShortVersionString": "1.0.3",
        "LSUIElement": True,  # Menu bar app — no Dock icon
        "NSHumanReadableCopyright": "MIT License — Thibault Patrouillat",
    },
}

setup(
    name=APP_NAME,
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
