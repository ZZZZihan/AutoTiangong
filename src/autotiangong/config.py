from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_EXTRA_FIELDS = {
    "R1": "0",
    "R2": "",
    "R3": "0",
    "R6": "0",
    "para": "00",
    "0MKKey": "123456",
}


@dataclass(frozen=True)
class LoginConfig:
    mode: str = "drcom"
    method: str = "GET"
    username_env: str = "CAMPUS_NET_USERNAME"
    password_env: str = "CAMPUS_NET_PASSWORD"
    extra_fields: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_EXTRA_FIELDS))
    success_markers: list[str] = field(default_factory=lambda: ["Dr.COMWebLoginID_3.htm", '"result":1'])
    failure_markers: list[str] = field(default_factory=lambda: ["Dr.COMWebLoginID_2.htm", '"result":0'])


@dataclass(frozen=True)
class AppConfig:
    portal_url: str
    connectivity_url: str = "http://connectivitycheck.gstatic.com/generate_204"
    connectivity_expected_status: int = 204
    check_interval_seconds: int = 60
    request_timeout_seconds: int = 8
    login: LoginConfig = field(default_factory=LoginConfig)


def load_config(path: str | Path) -> AppConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    login_raw = raw.get("login", {})
    login = LoginConfig(
        mode=str(login_raw.get("mode", "drcom")),
        method=str(login_raw.get("method", "GET")).upper(),
        username_env=str(login_raw.get("username_env", "CAMPUS_NET_USERNAME")),
        password_env=str(login_raw.get("password_env", "CAMPUS_NET_PASSWORD")),
        extra_fields=_string_dict(login_raw.get("extra_fields", DEFAULT_EXTRA_FIELDS)),
        success_markers=[str(item) for item in login_raw.get("success_markers", ["Dr.COMWebLoginID_3.htm", '"result":1'])],
        failure_markers=[str(item) for item in login_raw.get("failure_markers", ["Dr.COMWebLoginID_2.htm", '"result":0'])],
    )
    return AppConfig(
        portal_url=str(raw["portal_url"]),
        connectivity_url=str(raw.get("connectivity_url", "http://connectivitycheck.gstatic.com/generate_204")),
        connectivity_expected_status=int(raw.get("connectivity_expected_status", 204)),
        check_interval_seconds=int(raw.get("check_interval_seconds", 60)),
        request_timeout_seconds=int(raw.get("request_timeout_seconds", 8)),
        login=login,
    )


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_secret(env_name: str) -> str:
    value = os.environ.get(env_name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {env_name}")
    return value


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError("Expected object for login.extra_fields")
    return {str(key): str(item) for key, item in value.items()}

