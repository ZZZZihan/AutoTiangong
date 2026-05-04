#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.autotiangong.wifi-trigger"
TARGET_SSID="360WiFi-E07A5C"
TARGET_ROUTER_IP=""
TARGET_ROUTER_MAC=""
PYTHON_PATH=".venv/bin/python"
CONFIG_PATH="config.local.json"
ENV_FILE=".env"
LOG_DIR="logs"
STATE_DIR=".autotiangong-macos-wifi-trigger"
INTERVAL_SECONDS=10
MAX_RETRIES=6
RETRY_COOLDOWN_SECONDS=300
INSTALL_DEPS=0
FORCE_LOGIN=0
START_NOW=0

usage() {
    cat <<'USAGE'
Usage: install_macos_wifi_launch_agent.sh [options]

Installs a per-user macOS LaunchAgent that runs AutoTiangong when the current
Wi-Fi SSID becomes the target SSID.

Options:
  --project-dir PATH       Project directory. Defaults to this script's parent.
  --label LABEL            LaunchAgent label. Defaults to com.autotiangong.wifi-trigger.
  --ssid SSID              Target Wi-Fi SSID. Defaults to 360WiFi-E07A5C.
  --router-ip IP           Fallback router IP to match when macOS redacts SSID.
  --router-mac MAC         Optional fallback router MAC to match with --router-ip.
  --python-path PATH       Python executable, relative to project dir unless absolute.
  --config PATH            Config file, relative to project dir unless absolute.
  --env-file PATH          Env file, relative to project dir unless absolute.
  --log-dir PATH           Log directory, relative to project dir unless absolute.
  --state-dir PATH         State directory, relative to project dir unless absolute.
  --interval-seconds N     Poll interval. Defaults to 10.
  --max-retries N          Retry failed runs while still on target SSID. Defaults to 6.
  --retry-cooldown N       Seconds to wait before probing again after retry cap. Defaults to 300.
  --install-deps           Create .venv if needed and pip install -e the project.
  --force-login            Force login on new target connections and failed retries.
  --start-now              Start the LaunchAgent immediately after installation.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir)
            PROJECT_DIR="$2"
            shift 2
            ;;
        --label)
            LABEL="$2"
            shift 2
            ;;
        --ssid)
            TARGET_SSID="$2"
            shift 2
            ;;
        --router-ip)
            TARGET_ROUTER_IP="$2"
            shift 2
            ;;
        --router-mac)
            TARGET_ROUTER_MAC="$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')"
            shift 2
            ;;
        --python-path)
            PYTHON_PATH="$2"
            shift 2
            ;;
        --config)
            CONFIG_PATH="$2"
            shift 2
            ;;
        --env-file)
            ENV_FILE="$2"
            shift 2
            ;;
        --log-dir)
            LOG_DIR="$2"
            shift 2
            ;;
        --state-dir)
            STATE_DIR="$2"
            shift 2
            ;;
        --interval-seconds)
            INTERVAL_SECONDS="$2"
            shift 2
            ;;
        --max-retries)
            MAX_RETRIES="$2"
            shift 2
            ;;
        --retry-cooldown)
            RETRY_COOLDOWN_SECONDS="$2"
            shift 2
            ;;
        --install-deps)
            INSTALL_DEPS=1
            shift
            ;;
        --force-login)
            FORCE_LOGIN=1
            shift
            ;;
        --start-now)
            START_NOW=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 64
            ;;
    esac
done

resolve_path() {
    local value="$1"
    if [[ "$value" = /* ]]; then
        printf '%s\n' "$value"
    else
        printf '%s\n' "$PROJECT_DIR/$value"
    fi
}

xml_escape() {
    sed \
        -e 's/&/\&amp;/g' \
        -e 's/</\&lt;/g' \
        -e 's/>/\&gt;/g' \
        -e 's/"/\&quot;/g' \
        -e "s/'/\&apos;/g" <<< "$1"
}

require_number() {
    local name="$1"
    local value="$2"
    if [[ ! "$value" =~ ^[0-9]+$ || "$value" -eq 0 ]]; then
        echo "$name must be a positive integer: $value" >&2
        exit 64
    fi
}

require_number "--interval-seconds" "$INTERVAL_SECONDS"
require_number "--max-retries" "$MAX_RETRIES"
require_number "--retry-cooldown" "$RETRY_COOLDOWN_SECONDS"

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
RUNNER="$PROJECT_DIR/scripts/run_macos_wifi_trigger.sh"
PYTHON_ABS="$(resolve_path "$PYTHON_PATH")"
CONFIG_ABS="$(resolve_path "$CONFIG_PATH")"
ENV_ABS="$(resolve_path "$ENV_FILE")"
LOG_DIR_ABS="$(resolve_path "$LOG_DIR")"
STATE_DIR_ABS="$(resolve_path "$STATE_DIR")"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
SERVICE_TARGET="gui/$(id -u)/$LABEL"

if [[ ! -f "$RUNNER" ]]; then
    echo "Runner script was not found: $RUNNER" >&2
    exit 66
fi

if [[ "$INSTALL_DEPS" -eq 1 && ! -x "$PYTHON_ABS" ]]; then
    echo "Creating virtual environment: $PYTHON_ABS"
    python3 -m venv "$PROJECT_DIR/.venv"
fi

if [[ ! -x "$PYTHON_ABS" ]]; then
    echo "Python executable was not found or is not executable: $PYTHON_ABS" >&2
    echo "Run with --install-deps, or pass --python-path /path/to/python." >&2
    exit 66
fi

if [[ "$INSTALL_DEPS" -eq 1 ]]; then
    "$PYTHON_ABS" -m pip install --upgrade pip
    "$PYTHON_ABS" -m pip install -e "$PROJECT_DIR"
fi

if [[ ! -f "$CONFIG_ABS" ]]; then
    echo "Config file was not found: $CONFIG_ABS" >&2
    exit 66
fi
if [[ ! -f "$ENV_ABS" ]]; then
    echo "Env file was not found: $ENV_ABS" >&2
    exit 66
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR_ABS" "$STATE_DIR_ABS"
chmod +x "$RUNNER"

program_args=(
    "$RUNNER"
    --project-dir "$PROJECT_DIR"
    --ssid "$TARGET_SSID"
    --python-path "$PYTHON_ABS"
    --config "$CONFIG_ABS"
    --env-file "$ENV_ABS"
    --log-dir "$LOG_DIR_ABS"
    --state-dir "$STATE_DIR_ABS"
    --max-retries "$MAX_RETRIES"
    --retry-cooldown "$RETRY_COOLDOWN_SECONDS"
)
if [[ -n "$TARGET_ROUTER_IP" ]]; then
    program_args+=(--router-ip "$TARGET_ROUTER_IP")
fi
if [[ -n "$TARGET_ROUTER_MAC" ]]; then
    program_args+=(--router-mac "$TARGET_ROUTER_MAC")
fi
if [[ "$FORCE_LOGIN" -eq 1 ]]; then
    program_args+=(--force-login)
fi

{
    cat <<PLIST_HEADER
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$(xml_escape "$LABEL")</string>
  <key>ProgramArguments</key>
  <array>
PLIST_HEADER
    for arg in "${program_args[@]}"; do
        printf '    <string>%s</string>\n' "$(xml_escape "$arg")"
    done
    cat <<PLIST_FOOTER
  </array>
  <key>WorkingDirectory</key>
  <string>$(xml_escape "$PROJECT_DIR")</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>$INTERVAL_SECONDS</integer>
  <key>StandardOutPath</key>
  <string>$(xml_escape "$LOG_DIR_ABS/macos-wifi-launchd.out.log")</string>
  <key>StandardErrorPath</key>
  <string>$(xml_escape "$LOG_DIR_ABS/macos-wifi-launchd.err.log")</string>
</dict>
</plist>
PLIST_FOOTER
} > "$PLIST_PATH"

plutil -lint "$PLIST_PATH" >/dev/null

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "$SERVICE_TARGET" >/dev/null 2>&1 || true

echo "Installed LaunchAgent: $LABEL"
echo "Plist: $PLIST_PATH"
echo "Trigger log: $LOG_DIR_ABS/macos-wifi-trigger.log"

if [[ "$START_NOW" -eq 1 ]]; then
    launchctl kickstart -k "$SERVICE_TARGET"
    echo "Started LaunchAgent: $LABEL"
fi
