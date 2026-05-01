from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .config import TrafficGuardConfig

LOGGER = logging.getLogger(__name__)


class TrafficCounter(Protocol):
    def read_total_bytes(self, interface: str | None = None) -> int:
        """Return cumulative received + sent bytes for the host or interface."""


@dataclass(frozen=True)
class TrafficStatus:
    ok: bool
    message: str
    used_bytes: int | None = None
    limit_bytes: int | None = None
    account_label: str | None = None


class SystemTrafficCounter:
    def read_total_bytes(self, interface: str | None = None) -> int:
        system = platform.system().lower()
        if system == "windows":
            return _read_windows_total_bytes(interface)
        if system == "linux":
            return _read_linux_total_bytes(interface)
        if system == "darwin":
            return _read_darwin_total_bytes(interface)
        raise RuntimeError(f"Unsupported platform for traffic guard: {platform.system()}")


class TrafficGuard:
    def __init__(self, config: TrafficGuardConfig, counter: TrafficCounter | None = None) -> None:
        self.config = config
        self.counter = counter or SystemTrafficCounter()
        self.state_path = Path(config.state_path)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def activate(self, username: str) -> TrafficStatus:
        if not self.enabled:
            return TrafficStatus(True, "Traffic guard disabled.")

        try:
            total_bytes = self.counter.read_total_bytes(self.config.interface)
        except Exception as exc:  # noqa: BLE001 - fail-closed behavior is configurable.
            return self._counter_error(exc)

        state = self._load_state()
        account_key = _account_key(username)
        if state.get("account_key") != account_key:
            state = {
                "account_key": account_key,
                "account_label": _mask_username(username),
                "baseline_total_bytes": total_bytes,
                "last_total_bytes": total_bytes,
                "limit_bytes": self.config.limit_bytes,
                "updated_at": _utc_now(),
            }
            self._save_state(state)
            return TrafficStatus(
                True,
                "Traffic guard started for current account.",
                used_bytes=0,
                limit_bytes=self.config.limit_bytes,
                account_label=state["account_label"],
            )

        return self.check()

    def check(self) -> TrafficStatus:
        if not self.enabled:
            return TrafficStatus(True, "Traffic guard disabled.")

        state = self._load_state()
        if not state:
            return TrafficStatus(
                True,
                "Traffic guard is enabled; usage tracking will start after the next successful login.",
                used_bytes=None,
                limit_bytes=self.config.limit_bytes,
            )

        try:
            total_bytes = self.counter.read_total_bytes(self.config.interface)
        except Exception as exc:  # noqa: BLE001 - fail-closed behavior is configurable.
            return self._counter_error(exc)

        baseline = int(state.get("baseline_total_bytes", total_bytes))
        if total_bytes < baseline:
            LOGGER.info("Traffic counter reset detected; resetting traffic guard baseline.")
            baseline = total_bytes

        used_bytes = max(0, total_bytes - baseline)
        limit_bytes = self.config.limit_bytes
        state.update(
            {
                "baseline_total_bytes": baseline,
                "last_total_bytes": total_bytes,
                "used_bytes": used_bytes,
                "limit_bytes": limit_bytes,
                "updated_at": _utc_now(),
            }
        )
        self._save_state(state)

        account_label = _optional_text(state.get("account_label"))
        if used_bytes >= limit_bytes:
            return TrafficStatus(
                False,
                (
                    "Traffic guard limit reached"
                    f" ({format_bytes(used_bytes)} / {format_bytes(limit_bytes)}); stopping automatic login."
                ),
                used_bytes=used_bytes,
                limit_bytes=limit_bytes,
                account_label=account_label,
            )

        return TrafficStatus(
            True,
            f"Traffic guard usage: {format_bytes(used_bytes)} / {format_bytes(limit_bytes)}.",
            used_bytes=used_bytes,
            limit_bytes=limit_bytes,
            account_label=account_label,
        )

    def _counter_error(self, exc: Exception) -> TrafficStatus:
        message = f"Traffic guard could not read network counters: {exc}"
        if self.config.fail_closed:
            return TrafficStatus(False, f"{message}; stopping automatic login.")
        return TrafficStatus(True, f"{message}; continuing because fail_closed is false.")

    def _load_state(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Ignoring unreadable traffic guard state %s: %s", self.state_path, exc)
            return {}
        if not isinstance(raw, dict):
            LOGGER.warning("Ignoring invalid traffic guard state %s", self.state_path)
            return {}
        return raw

    def _save_state(self, state: dict[str, object]) -> None:
        if self.state_path.parent != Path("."):
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.2f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"


def _read_windows_total_bytes(interface: str | None) -> int:
    script = """
$adapter = [Environment]::GetEnvironmentVariable('AUTOTIANGONG_TRAFFIC_INTERFACE')
$items = Get-CimInstance Win32_PerfRawData_Tcpip_NetworkInterface
if ($adapter) {
  $items = $items | Where-Object { $_.Name -like "*$adapter*" }
}
$total = [uint64]0
foreach ($item in $items) {
  $total += [uint64]$item.BytesReceivedPersec + [uint64]$item.BytesSentPersec
}
Write-Output $total
""".strip()
    env = os.environ.copy()
    if interface:
        env["AUTOTIANGONG_TRAFFIC_INTERFACE"] = interface
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )
    return _parse_single_int(completed.stdout)


def _read_linux_total_bytes(interface: str | None) -> int:
    path = Path("/proc/net/dev")
    if not path.exists():
        raise RuntimeError("/proc/net/dev is not available")
    total = 0
    matched = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        raw_name, raw_values = line.split(":", 1)
        name = raw_name.strip()
        if interface and name != interface:
            continue
        values = raw_values.split()
        if len(values) < 16:
            continue
        total += int(values[0]) + int(values[8])
        matched = True
    if interface and not matched:
        raise RuntimeError(f"Network interface not found: {interface}")
    return total


def _read_darwin_total_bytes(interface: str | None) -> int:
    completed = subprocess.run(["netstat", "-ibn"], check=True, capture_output=True, text=True)
    return _parse_netstat_ibn(completed.stdout, interface)


def _parse_netstat_ibn(output: str, interface: str | None = None) -> int:
    lines = [line.split() for line in output.splitlines() if line.split()]
    if not lines:
        raise RuntimeError("netstat output was empty")
    header = lines[0]
    if "Ibytes" not in header or "Obytes" not in header:
        raise RuntimeError("netstat output did not include Ibytes/Obytes columns")

    totals_by_interface: dict[str, int] = {}
    for columns in lines[1:]:
        if len(columns) < 7:
            continue
        name = columns[0]
        if interface and name != interface:
            continue
        try:
            total = int(columns[-5]) + int(columns[-2])
        except ValueError:
            continue
        totals_by_interface[name] = max(totals_by_interface.get(name, 0), total)

    if interface and interface not in totals_by_interface:
        raise RuntimeError(f"Network interface not found: {interface}")
    return sum(totals_by_interface.values())


def _parse_single_int(output: str) -> int:
    match = re.search(r"\d+", output)
    if not match:
        raise RuntimeError("command output did not contain a byte counter")
    return int(match.group(0))


def _account_key(username: str) -> str:
    return hashlib.sha256(username.encode("utf-8")).hexdigest()


def _mask_username(username: str) -> str:
    if len(username) <= 4:
        return "***"
    return f"{username[:2]}***{username[-2:]}"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
