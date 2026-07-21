#!/bin/bash
#
# Tokease — Installation Script
#
# What this does:
#   1. Creates a Python virtualenv and installs dependencies
#   2. Optionally creates a macOS LaunchAgent for auto-start at login
#   3. Optionally launches the app immediately
#
# No API keys, no token, no network call. The tracker reads only local usage
# files official Claude apps write: the Claude desktop app's quota history
# (zero config) and, optionally, ~/.tokease/usage.json fed by Claude Code's
# statusline (wire with: bash statusline/install-statusline.sh).
#

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BANNER="================================================"
VENV_DIR="$SCRIPT_DIR/venv"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
LAUNCH_AGENT_PLIST="$LAUNCH_AGENT_DIR/com.tpatrouillat.tokease.plist"

echo "$BANNER"
echo "   Tokease — Installation"
echo "$BANNER"
echo ""

# --- Python check -----------------------------------------------------------
if ! command -v python3 &>/dev/null; then
    echo "Error: Python 3 is required but not installed." >&2
    echo "Easiest fix: brew install tpatrouillat/tap/tokease (ships its own Python)." >&2
    exit 1
fi
# macOS system python3 (Command Line Tools) can be 3.9, below our 3.10 minimum.
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Error: Python 3.10+ required, found $(python3 --version 2>&1)." >&2
    echo "Install a recent Python (brew install python) or use the Homebrew" >&2
    echo "package instead, which ships its own: brew install tpatrouillat/tap/tokease" >&2
    exit 1
fi
echo "Found $(python3 --version)"

# --- Virtual environment ----------------------------------------------------
echo ""
if [[ -d "$VENV_DIR" ]]; then
    echo "Reusing existing virtual environment at $VENV_DIR"
else
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q
echo "Dependencies installed."

chmod +x "$SCRIPT_DIR/tracker.py"

# --- Prerequisite reminder --------------------------------------------------
echo ""
echo "Prerequisite: a Claude Pro or Max plan."
echo "Zero config: keep the Claude desktop app running."
echo "Optional (reset countdowns): wire the Claude Code (>= 2.1.x) statusline with"
echo "  bash \"$SCRIPT_DIR/statusline/install-statusline.sh\""
echo ""

# --- LaunchAgent (auto-start) -----------------------------------------------
echo "$BANNER"
echo "   Auto-Start Setup"
echo "$BANNER"
echo ""
read -r -p "Start the tracker automatically at login? (y/n): " auto_start || auto_start="n"

if [[ "$auto_start" =~ ^[Yy]$ ]]; then
    mkdir -p "$LAUNCH_AGENT_DIR"

    # Unload any prior install before overwriting — avoids two trackers
    # racing for the menu bar slot on re-install.
    if [[ -f "$LAUNCH_AGENT_PLIST" ]]; then
        launchctl unload "$LAUNCH_AGENT_PLIST" 2>/dev/null || true
    fi

    # PATH includes Homebrew (Intel + Apple Silicon) + system bins so python3
    # and its dependencies resolve under the LaunchAgent's minimal environment.
    cat > "$LAUNCH_AGENT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tpatrouillat.tokease</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/python</string>
        <string>$SCRIPT_DIR/tracker.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF
    launchctl load "$LAUNCH_AGENT_PLIST"
    echo "LaunchAgent installed and loaded — it will also start at every login."
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

read -r -p "Start the tracker now? (y/n): " start_now || start_now="n"
if [[ "$start_now" =~ ^[Yy]$ ]]; then
    echo "Starting Tokease..."
    nohup "$VENV_DIR/bin/python" "$SCRIPT_DIR/tracker.py" >/dev/null 2>&1 &
fi

echo ""
echo "Look for a percentage badge (e.g. \"42%\") in the top-right of your menu bar."
echo "Click it to see your 5-hour and weekly limits (2 rings)."
echo ""
echo "Done!"
