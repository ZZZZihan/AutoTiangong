#!/usr/bin/env bash
set -euo pipefail

LABEL="com.autotiangong.wifi-trigger"
REMOVE_PLIST=1

usage() {
    cat <<'USAGE'
Usage: uninstall_macos_wifi_launch_agent.sh [options]

Options:
  --label LABEL       LaunchAgent label. Defaults to com.autotiangong.wifi-trigger.
  --keep-plist        Unload the LaunchAgent but keep its plist file.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --label)
            LABEL="$2"
            shift 2
            ;;
        --keep-plist)
            REMOVE_PLIST=0
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

PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true

if [[ "$REMOVE_PLIST" -eq 1 && -f "$PLIST_PATH" ]]; then
    rm "$PLIST_PATH"
fi

echo "Uninstalled LaunchAgent: $LABEL"
