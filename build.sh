#!/bin/bash
#
# Build Tokease as a standalone macOS .app
#
# Output: dist/Tokease.app
#
# Requirements: Python 3.10+, py2app
#

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/venv"
BANNER="================================================"

echo "$BANNER"
echo "   Tokease — Build"
echo "$BANNER"
echo ""

# --- Ensure venv exists ---
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installing build dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r requirements.txt -q
"$VENV_DIR/bin/pip" install py2app -q

# --- Clean previous builds ---
echo "Cleaning previous builds..."
rm -rf build dist

# --- Build ---
echo "Building .app bundle..."
"$VENV_DIR/bin/python" setup.py py2app 2>&1 | tail -5

echo ""
echo "$BANNER"
echo "   Build Complete"
echo "$BANNER"
echo ""

APP_PATH="dist/Tokease.app"
if [[ -d "$APP_PATH" ]]; then
    echo "App:  $APP_PATH"
    echo "Size: $(du -sh "$APP_PATH" | cut -f1)"
    echo ""
    echo "To test:  open \"$APP_PATH\""
    echo "To install: cp -r \"$APP_PATH\" /Applications/"
    echo ""
    echo "To create a DMG for distribution:"
    echo "  hdiutil create -volname 'Tokease' \\"
    echo "    -srcfolder dist -ov -format UDZO \\"
    echo "    'dist/Tokease.dmg'"
else
    echo "Build failed — check output above."
    exit 1
fi
