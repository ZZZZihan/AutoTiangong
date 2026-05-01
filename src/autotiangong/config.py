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
class AccountConfig:
    id: str
    username_env: str
    password_env: str


@dataclass(frozen=True)
class LoginConfig:
    mode: str = "drcom"
    method: str = "GET"
    username_env: str = "CAMPUS_NET_USERNAME"
    password_env: str = "CAMPUS_NET_PASSWORD"
    active_account_id: str | None = None
    active_account_state_path: str = ".autotiangong-active-account.json"
    accounts: list[AccountConfig] = field(default_factory=list)
    extra_fields: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_EXTRA_FIELDS))
    success_markers: list[str] = field(default_factory=lambda: ["Dr.COMWebLoginID_3.htm", '"result":1'])
    failure_markers: list[str] = field(default_factory=lambda: ["Dr.COMWebLoginID_2.htm", '"result":0'])
    quota_limit_markers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LogoutConfig:
    enabled: bool = False
    method: str = "GET"
    url: str | None = None
    extra_fields: dict[str, str] = field(default_factory=dict)
    success_markers: list[str] = field(default_factory=list)
    failure_markers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WebhookConfig:
    name: str
    kind: str = "generic"
    url_env: str | None = None
    url: str | None = None
    chat_id_env: str | None = None
    timeout_seconds: int = 8


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool = False
    smtp_host_env: str = "AUTOTIANGONG_SMTP_HOST"
    smtp_port: int = 587
    username_env: str | None = "AUTOTIANGONG_SMTP_USERNAME"
    password_env: str | None = "AUTOTIANGONG_SMTP_PASSWORD"
    from_env: str = "AUTOTIANGONG_EMAIL_FROM"
    to_env: str = "AUTOTIANGONG_EMAIL_TO"
    use_tls: bool = True


@dataclass(frozen=True)
class NotificationConfig:
    enabled: bool = False
    webhooks: list[WebhookConfig] = field(default_factory=list)
    email: EmailConfig = field(default_factory=EmailConfig)


@dataclass(frozen=True)
class TrafficGuardConfig:
    enabled: bool = False
    limit_bytes: int = int(4.9 * 1024 * 1024 * 1024)
    state_path: str = ".autotiangong-traffic.json"
    interface: str | None = None
    fail_closed: bool = True


@dataclass(frozen=True)
class AppConfig:
    portal_url: str
    connectivity_url: str = "http://connectivitycheck.gstatic.com/generate_204"
    connectivity_expected_status: int = 204
    check_interval_seconds: int = 60
    request_timeout_seconds: int = 8
    login: LoginConfig = field(default_factory=LoginConfig)
    logout: LogoutConfig = field(default_factory=LogoutConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    traffic_guard: TrafficGuardConfig = field(default_factory=TrafficGuardConfig)


def load_config(path: str | Path) -> AppConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    login_raw = raw.get("login", {})
    login = LoginConfig(
        mode=str(login_raw.get("mode", "drcom")),
        method=str(login_raw.get("method", "GET")).upper(),
        username_env=str(login_raw.get("username_env", "CAMPUS_NET_USERNAME")),
        password_env=str(login_raw.get("password_env", "CAMPUS_NET_PASSWORD")),
        active_account_id=_optional_string(login_raw.get("active_account_id")),
        active_account_state_path=str(login_raw.get("active_account_state_path", ".autotiangong-active-account.json")),
        accounts=_load_accounts(login_raw),
        extra_fields=_string_dict(login_raw.get("extra_fields", DEFAULT_EXTRA_FIELDS)),
        success_markers=[str(item) for item in login_raw.get("success_markers", ["Dr.COMWebLoginID_3.htm", '"result":1'])],
        failure_markers=[str(item) for item in login_raw.get("failure_markers", ["Dr.COMWebLoginID_2.htm", '"result":0'])],
        quota_limit_markers=[str(item) for item in login_raw.get("quota_limit_markers", [])],
    )
    _validate_active_account(login)
    logout = _load_logout(raw.get("logout", {}))
    notifications = _load_notifications(raw.get("notifications", {}))
    traffic_guard = _load_traffic_guard(raw.get("traffic_guard", {}))
    return AppConfig(
        portal_url=str(raw["portal_url"]),
        connectivity_url=str(raw.get("connectivity_url", "http://connectivitycheck.gstatic.com/generate_204")),
        connectivity_expected_status=int(raw.get("connectivity_expected_status", 204)),
        check_interval_seconds=int(raw.get("check_interval_seconds", 60)),
        request_timeout_seconds=int(raw.get("request_timeout_seconds", 8)),
        login=login,
        logout=logout,
        notifications=notifications,
        traffic_guard=traffic_guard,
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


def _load_accounts(login_raw: dict[str, Any]) -> list[AccountConfig]:
    raw_accounts = login_raw.get("accounts")
    if raw_accounts is None:
        return [
            AccountConfig(
                id="default",
                username_env=str(login_raw.get("username_env", "CAMPUS_NET_USERNAME")),
                password_env=str(login_raw.get("password_env", "CAMPUS_NET_PASSWORD")),
            )
        ]
    if not isinstance(raw_accounts, list):
        raise TypeError("Expected array for login.accounts")

    accounts = []
    seen_ids: set[str] = set()
    for raw_account in raw_accounts:
        if not isinstance(raw_account, dict):
            raise TypeError("Expected object entries for login.accounts")
        account = AccountConfig(
            id=_required_nonempty_string(raw_account.get("id"), "login.accounts[].id"),
            username_env=_required_nonempty_string(raw_account.get("username_env"), "login.accounts[].username_env"),
            password_env=_required_nonempty_string(raw_account.get("password_env"), "login.accounts[].password_env"),
        )
        if account.id in seen_ids:
            raise ValueError(f"Duplicate login account id: {account.id}")
        seen_ids.add(account.id)
        accounts.append(account)

    if not accounts:
        raise ValueError("login.accounts must contain at least one account")
    return accounts


def _validate_active_account(login: LoginConfig) -> None:
    if login.active_account_id is None:
        return
    account_ids = {account.id for account in login.accounts}
    if login.active_account_id not in account_ids:
        valid_ids = ", ".join(account_ids)
        raise ValueError(f"login.active_account_id {login.active_account_id!r} is not in login.accounts. Valid ids: {valid_ids}")


def _load_logout(value: Any) -> LogoutConfig:
    if value is None:
        return LogoutConfig()
    if not isinstance(value, dict):
        raise TypeError("Expected object for logout")

    return LogoutConfig(
        enabled=bool(value.get("enabled", False)),
        method=str(value.get("method", "GET")).upper(),
        url=_optional_string(value.get("url")),
        extra_fields=_string_dict(value.get("extra_fields", {})),
        success_markers=[str(item) for item in value.get("success_markers", [])],
        failure_markers=[str(item) for item in value.get("failure_markers", [])],
    )


def _load_notifications(value: Any) -> NotificationConfig:
    if value is None:
        return NotificationConfig()
    if not isinstance(value, dict):
        raise TypeError("Expected object for notifications")

    webhooks = _load_webhooks(value.get("webhooks", []))
    email = _load_email(value.get("email", {}))
    return NotificationConfig(
        enabled=bool(value.get("enabled", False)),
        webhooks=webhooks,
        email=email,
    )


def _load_webhooks(value: Any) -> list[WebhookConfig]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("Expected array for notifications.webhooks")

    webhooks = []
    for index, raw_webhook in enumerate(value):
        if not isinstance(raw_webhook, dict):
            raise TypeError("Expected object entries for notifications.webhooks")
        name = str(raw_webhook.get("name", f"webhook-{index + 1}"))
        webhooks.append(
            WebhookConfig(
                name=name,
                kind=str(raw_webhook.get("kind", "generic")).lower(),
                url_env=_optional_string(raw_webhook.get("url_env")),
                url=_optional_string(raw_webhook.get("url")),
                chat_id_env=_optional_string(raw_webhook.get("chat_id_env")),
                timeout_seconds=int(raw_webhook.get("timeout_seconds", 8)),
            )
        )
    return webhooks


def _load_email(value: Any) -> EmailConfig:
    if value is None:
        return EmailConfig()
    if not isinstance(value, dict):
        raise TypeError("Expected object for notifications.email")

    return EmailConfig(
        enabled=bool(value.get("enabled", False)),
        smtp_host_env=str(value.get("smtp_host_env", "AUTOTIANGONG_SMTP_HOST")),
        smtp_port=int(value.get("smtp_port", 587)),
        username_env=_optional_string(value.get("username_env", "AUTOTIANGONG_SMTP_USERNAME")),
        password_env=_optional_string(value.get("password_env", "AUTOTIANGONG_SMTP_PASSWORD")),
        from_env=str(value.get("from_env", "AUTOTIANGONG_EMAIL_FROM")),
        to_env=str(value.get("to_env", "AUTOTIANGONG_EMAIL_TO")),
        use_tls=bool(value.get("use_tls", True)),
    )


def _load_traffic_guard(value: Any) -> TrafficGuardConfig:
    if value is None:
        return TrafficGuardConfig()
    if not isinstance(value, dict):
        raise TypeError("Expected object for traffic_guard")

    return TrafficGuardConfig(
        enabled=bool(value.get("enabled", False)),
        limit_bytes=_traffic_limit_bytes(value),
        state_path=str(value.get("state_path", ".autotiangong-traffic.json")),
        interface=_optional_string(value.get("interface")),
        fail_closed=bool(value.get("fail_closed", True)),
    )


def _traffic_limit_bytes(value: dict[str, Any]) -> int:
    if "limit_bytes" in value:
        return int(value["limit_bytes"])
    limit_gib = float(value.get("limit_gib", 4.9))
    return int(limit_gib * 1024 * 1024 * 1024)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_nonempty_string(value: Any, field_name: str) -> str:
    text = _optional_string(value)
    if text is None:
        raise ValueError(f"Missing required field: {field_name}")
    return text
