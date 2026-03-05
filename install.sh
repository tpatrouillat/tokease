#!/bin/bash
#
# Claude Usage Tracker — Installation Script
#
# What this does:
#   1. Creates a Python virtualenv and installs rumps
#   2. Optionally creates a macOS LaunchAgent for auto-start at login
#   3. Optionally launches the app immediately
#
# No API keys are needed — the tracker reads Claude Code's OAuth token
# directly from the macOS Keychain (set by `claude login`).
#

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BANNER="================================================"
VENV_DIR="$SCRIPT_DIR/venv"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
LAUNCH_AGENT_PLIST="$LAUNCH_AGENT_DIR/com.claude-usage-tracker.plist"

echo "$BANNER"
echo "   Claude Usage Tracker — Installation"
echo "$BANNER"
echo ""

# --- Python check -----------------------------------------------------------
if ! command -v python3 &>/dev/null; then
    echo "Error: Python 3 is required but not installed." >&2
    exit 1
fi
echo "Found $(python3 --version)"

# --- Virtual environment ----------------------------------------------------
echo ""
echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR"

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q
echo "Dependencies installed."

chmod +x "$SCRIPT_DIR/tracker.py"

# --- Prerequisite reminder --------------------------------------------------
echo ""
echo "Prerequisite: Claude Code must be installed and logged in."
echo "If you haven't yet, run:  claude login"
echo ""

# --- LaunchAgent (auto-start) -----------------------------------------------
echo "$BANNER"
echo "   Auto-Start Setup"
echo "$BANNER"
echo ""
read -r -p "Start the tracker automatically at login? (y/n): " auto_start

if [[ "$auto_start" =~ ^[Yy]$ ]]; then
    mkdir -p "$LAUNCH_AGENT_DIR"

    # PATH is explicitly set so `security` CLI is found even in a stripped
    # LaunchAgent environment (macOS agents don't inherit the user's PATH).
    cat > "$LAUNCH_AGENT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude-usage-tracker</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/python</string>
        <string>$SCRIPT_DIR/tracker.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF
    echo "LaunchAgent created: $LAUNCH_AGENT_PLIST"
    echo "The tracker will start automatically at next login."
    echo "To load it now without relogging:"
    echo "  launchctl load \"$LAUNCH_AGENT_PLIST\""
fi

# --- Done -------------------------------------------------------------------
echo ""
echo "$BANNER"
echo "   Installation Complete"
echo "$BANNER"
echo ""
echo "To start manually:"
echo "  \"$VENV_DIR/bin/python\" \"$SCRIPT_DIR/tracker.py\""
echo ""

read -r -p "Start the tracker now? (y/n): " start_now
if [[ "$start_now" =~ ^[Yy]$ ]]; then
    echo "Starting Claude Usage Tracker..."
    nohup "$VENV_DIR/bin/python" "$SCRIPT_DIR/tracker.py" >/dev/null 2>&1 &
    echo "Running — look for it in your menu bar."
fi

echo ""
echo "Done!"
