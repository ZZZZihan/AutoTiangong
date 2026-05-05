#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_SSID="360WiFi-E07A5C"
TARGET_ROUTER_IP=""
TARGET_ROUTER_MAC=""
PYTHON_PATH=".venv/bin/python"
CONFIG_PATH="config.local.json"
ENV_FILE=".env"
LOG_DIR="logs"
STATE_DIR=".autotiangong-macos-wifi-trigger"
MAX_RETRIES=6
RETRY_COOLDOWN_SECONDS=300
SUCCESS_LOG_INTERVAL_SECONDS=300
FORCE_LOGIN=0

usage() {
    cat <<'USAGE'
Usage: run_macos_wifi_trigger.sh [options]

Options:
  --project-dir PATH      Project directory. Defaults to this script's parent.
  --ssid SSID             Wi-Fi SSID that should trigger AutoTiangong.
  --router-ip IP          Fallback router IP to match when macOS redacts SSID.
  --router-mac MAC        Optional fallback router MAC to match with --router-ip.
  --python-path PATH      Python executable, relative to project dir unless absolute.
  --config PATH           Config file, relative to project dir unless absolute.
  --env-file PATH         Env file, relative to project dir unless absolute.
  --log-dir PATH          Log directory, relative to project dir unless absolute.
  --state-dir PATH        State directory, relative to project dir unless absolute.
  --max-retries N         Retry failed runs while still on target SSID. Defaults to 6.
  --retry-cooldown N      Seconds to wait before probing again after retry cap. Defaults to 300.
  --success-log-interval N
                          Seconds between repeated successful check log entries. Defaults to 300.
  --force-login           Pass --force-login on a new target connection and failed retries.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir)
            PROJECT_DIR="$2"
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
        --max-retries)
            MAX_RETRIES="$2"
            shift 2
            ;;
        --retry-cooldown)
            RETRY_COOLDOWN_SECONDS="$2"
            shift 2
            ;;
        --success-log-interval)
            SUCCESS_LOG_INTERVAL_SECONDS="$2"
            shift 2
            ;;
        --force-login)
            FORCE_LOGIN=1
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

log_line() {
    local message="$1"
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$message" >> "$LOG_FILE"
}

wifi_device() {
    networksetup -listallhardwareports 2>/dev/null | awk '
        $0 == "Hardware Port: Wi-Fi" {
            getline
            sub(/^Device: /, "")
            print
            exit
        }
    '
}

current_ssid() {
    local device="$1"
    local output ssid
    output="$(networksetup -getairportnetwork "$device" 2>/dev/null || true)"
    case "$output" in
        "Current Wi-Fi Network: "*)
            ssid="${output#*: }"
            if [[ -n "$ssid" && "$ssid" != "<redacted>" ]]; then
                printf '%s\n' "$ssid"
                return 0
            fi
            ;;
    esac
    ipconfig getsummary "$device" 2>/dev/null | awk -F ' : ' '
        $1 ~ /^[[:space:]]*SSID$/ && $2 != "<redacted>" {
            print $2
            exit
        }
    '
}

current_router_ip() {
    local device="$1"
    ipconfig getoption "$device" router 2>/dev/null | awk 'NF {print $1; exit}'
}

current_router_mac() {
    local router_ip="$1"
    if [[ -z "$router_ip" ]]; then
        return 0
    fi
    ping -c 1 -W 1000 "$router_ip" >/dev/null 2>&1 || true
    arp -n "$router_ip" 2>/dev/null | awk '
        / at / {
            for (i = 1; i <= NF; i++) {
                if ($i == "at" && (i + 1) <= NF) {
                    print tolower($(i + 1))
                    exit
                }
            }
        }
    '
}

network_identity() {
    local device="$1"
    local ssid router_ip router_mac
    ssid="$(current_ssid "$device")"
    if [[ -n "$ssid" ]]; then
        printf 'ssid:%s\n' "$ssid"
        return 0
    fi

    router_ip="$(current_router_ip "$device")"
    router_mac="$(current_router_mac "$router_ip")"
    if [[ -n "$router_ip" ]]; then
        printf 'router:%s:%s\n' "$router_ip" "$router_mac"
        return 0
    fi

    printf '\n'
}

matches_target_network() {
    local identity="$1"
    case "$identity" in
        "ssid:$TARGET_SSID")
            return 0
            ;;
        "router:$TARGET_ROUTER_IP:"*)
            if [[ -z "$TARGET_ROUTER_IP" ]]; then
                return 1
            fi
            if [[ -z "$TARGET_ROUTER_MAC" || "$identity" == "router:$TARGET_ROUTER_IP:$TARGET_ROUTER_MAC" ]]; then
                return 0
            fi
            ;;
    esac
    return 1
}

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
PYTHON_ABS="$(resolve_path "$PYTHON_PATH")"
CONFIG_ABS="$(resolve_path "$CONFIG_PATH")"
ENV_ABS="$(resolve_path "$ENV_FILE")"
LOG_DIR_ABS="$(resolve_path "$LOG_DIR")"
STATE_DIR_ABS="$(resolve_path "$STATE_DIR")"
LOG_FILE="$LOG_DIR_ABS/macos-wifi-trigger.log"
LOCK_DIR="$STATE_DIR_ABS/lock"
LAST_SSID_FILE="$STATE_DIR_ABS/last_ssid"
RETRY_FILE="$STATE_DIR_ABS/retry_count"
LAST_FAILURE_FILE="$STATE_DIR_ABS/last_failure_epoch"
LAST_SUCCESS_LOG_FILE="$STATE_DIR_ABS/last_success_log_epoch"
SUPPRESSED_SUCCESS_FILE="$STATE_DIR_ABS/suppressed_success_count"
RUN_OUTPUT=""

mkdir -p "$LOG_DIR_ABS" "$STATE_DIR_ABS"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    log_line "Another Wi-Fi trigger run is still active; skipping."
    exit 0
fi
trap 'if [[ -n "${RUN_OUTPUT:-}" ]]; then rm -f "$RUN_OUTPUT"; fi; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

if [[ ! "$MAX_RETRIES" =~ ^[0-9]+$ || "$MAX_RETRIES" -eq 0 ]]; then
    log_line "Invalid --max-retries value: $MAX_RETRIES"
    exit 64
fi
if [[ ! "$RETRY_COOLDOWN_SECONDS" =~ ^[0-9]+$ || "$RETRY_COOLDOWN_SECONDS" -eq 0 ]]; then
    log_line "Invalid --retry-cooldown value: $RETRY_COOLDOWN_SECONDS"
    exit 64
fi
if [[ ! "$SUCCESS_LOG_INTERVAL_SECONDS" =~ ^[0-9]+$ || "$SUCCESS_LOG_INTERVAL_SECONDS" -eq 0 ]]; then
    log_line "Invalid --success-log-interval value: $SUCCESS_LOG_INTERVAL_SECONDS"
    exit 64
fi

for required_path in "$PYTHON_ABS" "$CONFIG_ABS" "$ENV_ABS"; do
    if [[ ! -e "$required_path" ]]; then
        log_line "Required path does not exist: $required_path"
        exit 66
    fi
done

device="$(wifi_device)"
if [[ -z "$device" ]]; then
    log_line "No Wi-Fi device found."
    exit 0
fi

identity="$(network_identity "$device")"
last_identity="$(cat "$LAST_SSID_FILE" 2>/dev/null || true)"
retry_count="$(cat "$RETRY_FILE" 2>/dev/null || printf '0')"
if [[ ! "$retry_count" =~ ^[0-9]+$ ]]; then
    retry_count=0
fi
first_target_run=0

if ! matches_target_network "$identity"; then
    printf '%s\n' "$identity" > "$LAST_SSID_FILE"
    printf '0\n' > "$RETRY_FILE"
    rm -f "$LAST_FAILURE_FILE"
    rm -f "$LAST_SUCCESS_LOG_FILE" "$SUPPRESSED_SUCCESS_FILE"
    log_line "Current Wi-Fi identity is '${identity:-<none>}'; waiting for '$TARGET_SSID'."
    exit 0
fi

if [[ "$last_identity" != "$identity" ]]; then
    first_target_run=1
    retry_count=0
    rm -f "$LAST_FAILURE_FILE"
fi

if [[ "$last_identity" == "$identity" && "$retry_count" -ge "$MAX_RETRIES" ]]; then
    now_epoch="$(date +%s)"
    last_failure_epoch="$(cat "$LAST_FAILURE_FILE" 2>/dev/null || printf '0')"
    if [[ ! "$last_failure_epoch" =~ ^[0-9]+$ ]]; then
        last_failure_epoch=0
    fi
    if (( now_epoch - last_failure_epoch < RETRY_COOLDOWN_SECONDS )); then
        log_line "Reached retry limit ($MAX_RETRIES) for current '$TARGET_SSID' connection ($identity); cooling down."
        exit 0
    fi
    retry_count=0
    printf '0\n' > "$RETRY_FILE"
    log_line "Retry cooldown elapsed for current '$TARGET_SSID' connection ($identity); probing again."
fi

args=(
    -m autotiangong
    --config "$CONFIG_ABS"
    --env-file "$ENV_ABS"
    --once
    --auto-switch
    --verbose
)
if [[ "$FORCE_LOGIN" -eq 1 && ( "$first_target_run" -eq 1 || "$retry_count" -gt 0 ) ]]; then
    args+=(--force-login)
fi

RUN_OUTPUT="$(mktemp "$STATE_DIR_ABS/run-output.XXXXXX")"
set +e
(
    cd "$PROJECT_DIR"
    PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_ABS" "${args[@]}"
) > "$RUN_OUTPUT" 2>&1
exit_code=$?
set -e

printf '%s\n' "$identity" > "$LAST_SSID_FILE"
if [[ "$exit_code" -eq 0 ]]; then
    printf '0\n' > "$RETRY_FILE"
    rm -f "$LAST_FAILURE_FILE"
    significant_output=0
    if grep -Eq "Force login requested|Connectivity check indicates captive|attempting login|Using authorized account id|Prepared Dr\\.COM login request|Kernel login|Active account switched|Active account state aligned|marked unavailable|Login failed|Traffic guard limit reached|Traffic guard could not|Traffic guard started|account unavailable|AutoTiangong stopped" "$RUN_OUTPUT"; then
        significant_output=1
    fi

    now_epoch="$(date +%s)"
    last_success_log_epoch="$(cat "$LAST_SUCCESS_LOG_FILE" 2>/dev/null || printf '0')"
    if [[ ! "$last_success_log_epoch" =~ ^[0-9]+$ ]]; then
        last_success_log_epoch=0
    fi
    suppressed_success_count="$(cat "$SUPPRESSED_SUCCESS_FILE" 2>/dev/null || printf '0')"
    if [[ ! "$suppressed_success_count" =~ ^[0-9]+$ ]]; then
        suppressed_success_count=0
    fi

    should_log_success=0
    if [[ "$first_target_run" -eq 1 || "$significant_output" -eq 1 ]]; then
        should_log_success=1
    elif (( now_epoch - last_success_log_epoch >= SUCCESS_LOG_INTERVAL_SECONDS )); then
        should_log_success=1
    fi

    if [[ "$should_log_success" -eq 1 ]]; then
        suppressed_note=""
        if [[ "$suppressed_success_count" -gt 0 ]]; then
            suppressed_note=" Suppressed $suppressed_success_count repeated successful check(s) since last logged success."
        fi
        log_line "Matched '$TARGET_SSID' as $identity; running AutoTiangong connectivity/login check with $PYTHON_ABS.$suppressed_note"
        cat "$RUN_OUTPUT" >> "$LOG_FILE"
        log_line "AutoTiangong completed successfully."
        printf '%s\n' "$now_epoch" > "$LAST_SUCCESS_LOG_FILE"
        printf '0\n' > "$SUPPRESSED_SUCCESS_FILE"
    else
        suppressed_success_count=$((suppressed_success_count + 1))
        printf '%s\n' "$suppressed_success_count" > "$SUPPRESSED_SUCCESS_FILE"
    fi
    exit 0
fi

retry_count=$((retry_count + 1))
printf '%s\n' "$retry_count" > "$RETRY_FILE"
date +%s > "$LAST_FAILURE_FILE"
log_line "Matched '$TARGET_SSID' as $identity; running AutoTiangong connectivity/login check with $PYTHON_ABS."
cat "$RUN_OUTPUT" >> "$LOG_FILE"
log_line "AutoTiangong exited with code $exit_code; retry $retry_count/$MAX_RETRIES."
exit "$exit_code"
