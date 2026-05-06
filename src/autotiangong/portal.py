from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import random
from collections.abc import Iterable
from dataclasses import dataclass

from .config import AppConfig
from .drcom import build_login_params, parse_drcom_settings
from .http_client import HttpClient, HttpResponse

LOGGER = logging.getLogger(__name__)

SENSITIVE_QUERY_KEYS = {"ddddd", "upass", "password", "passwd", "pwd", "username", "user"}


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    message: str
    status: int | None = None
    url: str | None = None
    quota_limited: bool = False
    account_unavailable: bool = False
    reason: str = "unknown"


@dataclass(frozen=True)
class LogoutResult:
    ok: bool
    message: str
    status: int | None = None
    url: str | None = None
    skipped: bool = False


@dataclass(frozen=True)
class PortalSessionStatus:
    checked: bool
    authenticated: bool
    message: str
    username: str | None = None
    status: int | None = None
    url: str | None = None


class CampusPortal:
    def __init__(self, config: AppConfig, http: HttpClient | None = None) -> None:
        self.config = config
        self.http = http or HttpClient(timeout_seconds=config.request_timeout_seconds)

    def is_online(self) -> bool:
        try:
            response = self.http.get(self.config.connectivity_url)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            LOGGER.info("Connectivity check failed: %s", exc)
            return False

        if response.status != self.config.connectivity_expected_status:
            LOGGER.info(
                "Connectivity check returned HTTP %s from %s, expected %s",
                response.status,
                response.url,
                self.config.connectivity_expected_status,
            )
            return False
        return True

    def session_status(self) -> PortalSessionStatus:
        if self.config.login.mode.lower() != "drcom":
            return PortalSessionStatus(
                checked=False,
                authenticated=False,
                message=f"Unsupported session check mode: {self.config.login.mode}",
            )

        try:
            response = self.http.get(self.config.portal_url)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            return PortalSessionStatus(
                checked=False,
                authenticated=False,
                message=f"Dr.COM session check failed: {exc}",
            )

        username = _extract_session_uid(f"{response.url}\n{response.text}")
        if username:
            return PortalSessionStatus(
                checked=True,
                authenticated=True,
                message=f"Dr.COM session is active for {_mask_username(username)}.",
                username=username,
                status=response.status,
                url=response.url,
            )

        return PortalSessionStatus(
            checked=True,
            authenticated=False,
            message="Dr.COM portal did not report an active uid/session.",
            status=response.status,
            url=response.url,
        )

    def login(self, username: str, password: str, dry_run: bool = False) -> LoginResult:
        if self.config.login.mode.lower() != "drcom":
            return LoginResult(False, f"Unsupported login mode: {self.config.login.mode}")

        portal_response = self.http.get(self.config.portal_url)
        settings = parse_drcom_settings(self.config.portal_url, portal_response.text)
        params = build_login_params(settings, username, password, self.config.login.extra_fields)
        login_url = settings.login_url

        safe_params = {key: _redact(value) for key, value in params.items()}
        safe_params[settings.username_field] = _mask_username(username)
        safe_params[settings.password_field] = "***"
        LOGGER.info("Prepared Dr.COM login request: %s %s %s", self.config.login.method, login_url, safe_params)

        if dry_run:
            return LoginResult(
                True,
                f"Dry run prepared Dr.COM request to {login_url}",
                portal_response.status,
                login_url,
                reason="dry_run",
            )

        response = self.http.submit(
            self.config.login.method,
            login_url,
            params,
            encoding=settings.charset,
            headers={"Referer": self.config.portal_url},
        )
        result = _classify_login_response(
            response,
            self.config,
            settings.success_marker,
            settings.failure_marker,
            sensitive_query_keys={settings.username_field, settings.password_field},
        )
        if result.reason == "unknown_failure" and self.config.login.fallback_to_kernel:
            LOGGER.info("Portal login result was unclear; trying Dr.COM kernel login fallback.")
            fallback_result = self._kernel_login(username, password, settings.charset)
            if fallback_result.reason != "unknown_failure":
                return fallback_result
        return result

    def logout(self, username: str, dry_run: bool = False) -> LogoutResult:
        if not self.config.logout.enabled:
            return LogoutResult(True, "Logout is disabled.", skipped=True)
        if self.config.login.mode.lower() != "drcom":
            return LogoutResult(False, f"Unsupported logout mode for login mode: {self.config.login.mode}")

        portal_response = self.http.get(self.config.portal_url)
        settings = parse_drcom_settings(self.config.portal_url, portal_response.text)
        logout_url = self.config.logout.url or _derive_logout_url(settings.login_url)
        params = dict(settings.login_params or {})
        params.update(self.config.logout.extra_fields)
        params[settings.username_field] = username

        safe_params = {key: _redact(value) for key, value in params.items()}
        safe_params[settings.username_field] = _mask_username(username)
        LOGGER.info("Prepared Dr.COM logout request: %s %s %s", self.config.logout.method, logout_url, safe_params)

        if dry_run:
            return LogoutResult(True, f"Dry run prepared Dr.COM logout request to {logout_url}", portal_response.status, logout_url)

        response = self.http.submit(
            self.config.logout.method,
            logout_url,
            params,
            encoding=settings.charset,
            headers={"Referer": self.config.portal_url},
        )
        return _classify_logout_response(response, self.config.logout.success_markers, self.config.logout.failure_markers)

    def _kernel_login(self, username: str, password: str, encoding: str) -> LoginResult:
        login_url = _kernel_url(self.config.portal_url, self.config.login.kernel_port, "drcom/login")
        query_items = [
            ("callback", "drcom_login"),
            ("DDDDD", username),
            ("upass", password),
            ("0MKKey", self.config.login.extra_fields.get("0MKKey", "123456")),
            ("R1", self.config.login.extra_fields.get("R1", "0")),
            ("R2", self.config.login.extra_fields.get("R2", "")),
            ("R3", self.config.login.extra_fields.get("R3", "0")),
            ("R6", self.config.login.extra_fields.get("R6", "0")),
            ("para", self.config.login.extra_fields.get("para", "00")),
            ("v6ip", ""),
            ("terminal_type", "1"),
            ("lang", "en"),
            ("jsVersion", "4.2.1"),
            ("v", str(random.randint(500, 10499))),
            ("lang", "en"),
        ]
        separator = "&" if urllib.parse.urlsplit(login_url).query else "?"
        response = self.http.get(
            f"{login_url}{separator}{urllib.parse.urlencode(query_items, encoding=encoding, errors='replace')}",
            headers={"Referer": self.config.portal_url},
        )
        return _classify_kernel_login_response(response, sensitive_query_keys={"DDDDD", "upass"})


def _classify_login_response(
    response: HttpResponse,
    config: AppConfig,
    portal_success_marker: str,
    portal_failure_marker: str,
    sensitive_query_keys: Iterable[str] = (),
) -> LoginResult:
    text = _compact(response.text)
    text_casefold = text.casefold()
    failure_markers = [portal_failure_marker, *config.login.failure_markers]
    success_markers = [portal_success_marker, *config.login.success_markers]
    safe_url = _redact_url(response.url, sensitive_query_keys)

    for marker in config.login.quota_limit_markers:
        compact_marker = _compact(marker).casefold()
        if compact_marker and compact_marker in text_casefold:
            return LoginResult(
                False,
                f"Login response indicated account unavailable by quota limit marker: {marker}",
                response.status,
                safe_url,
                quota_limited=True,
                account_unavailable=True,
                reason="quota_limited",
            )

    for marker in config.login.account_unavailable_markers:
        compact_marker = _compact(marker).casefold()
        if compact_marker and compact_marker in text_casefold:
            return LoginResult(
                False,
                f"Login response indicated account unavailable: {marker}",
                response.status,
                safe_url,
                account_unavailable=True,
                reason="account_unavailable",
            )

    for marker in failure_markers:
        compact_marker = _compact(marker).casefold()
        if compact_marker and compact_marker in text_casefold:
            return LoginResult(
                False,
                f"Login response contained failure marker: {marker}",
                response.status,
                safe_url,
                reason="auth_failed",
            )

    for marker in success_markers:
        compact_marker = _compact(marker).casefold()
        if compact_marker and compact_marker in text_casefold:
            return LoginResult(
                True,
                f"Login response contained success marker: {marker}",
                response.status,
                safe_url,
                reason="success",
            )

    if re.search(r"login_result['\"]?\s*:\s*[12]", text) or re.search(r"result['\"]?\s*:\s*1", text):
        return LoginResult(True, "Login response looked successful", response.status, safe_url, reason="success")

    if 200 <= response.status < 400:
        return LoginResult(
            False,
            "Login request completed but no success marker was found",
            response.status,
            safe_url,
            reason="unknown_failure",
        )

    return LoginResult(
        False,
        f"Login request failed with HTTP {response.status}",
        response.status,
        safe_url,
        reason="http_error",
    )


def _classify_kernel_login_response(
    response: HttpResponse,
    sensitive_query_keys: Iterable[str] = (),
) -> LoginResult:
    text = response.text
    compact_text = _compact(text)
    text_casefold = compact_text.casefold()
    safe_url = _redact_url(response.url, sensitive_query_keys)
    payload = _extract_jsonp_payload(text)

    if payload:
        result = str(payload.get("result", "")).casefold()
        message = str(payload.get("msg") or payload.get("message") or payload)
        if result in {"1", "ok", "true"}:
            return LoginResult(True, "Kernel login succeeded.", response.status, safe_url, reason="success")
        if result in {"0", "false", "fail", "failed"}:
            return LoginResult(
                False,
                f"Kernel login failed: {message}",
                response.status,
                safe_url,
                account_unavailable=True,
                reason="auth_failed",
            )

    if "dr.comwebloginid_3.htm" in text_casefold:
        return LoginResult(True, "Kernel login returned success page.", response.status, safe_url, reason="success")

    if "dr.comwebloginid_2.htm" in text_casefold:
        return LoginResult(False, "Kernel login returned failure page.", response.status, safe_url, reason="auth_failed")

    if 200 <= response.status < 400:
        return LoginResult(False, "Kernel login completed but no success marker was found", response.status, safe_url)

    return LoginResult(False, f"Kernel login failed with HTTP {response.status}", response.status, safe_url, reason="http_error")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _extract_jsonp_payload(text: str) -> dict[str, object] | None:
    import json

    stripped = text.strip().rstrip(";")
    match = re.match(r"^[A-Za-z_$][\w$]*\((.*)\)$", stripped, re.S)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_session_uid(text: str) -> str | None:
    patterns = [
        r"(?:^|[^\w])uid\b\s*=\s*['\"]?([^'\"&;<>\s]+)",
        r"['\"]uid['\"]\s*:\s*['\"]([^'\"]+)",
        r"[?&]uid=([^&\s#]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        value = urllib.parse.unquote(match.group(1)).strip()
        if value and value.casefold() not in {"0", "null", "undefined", "none"}:
            return value
    return None


def _kernel_url(portal_url: str, port: int | None, path: str) -> str:
    parts = urllib.parse.urlsplit(portal_url)
    path = path.lstrip("/")
    netloc = parts.netloc
    if port is not None:
        netloc = f"{parts.hostname}:{port}"
    return urllib.parse.urlunsplit((parts.scheme or "http", netloc, f"/{path}", "", ""))


def _classify_logout_response(
    response: HttpResponse,
    success_markers: list[str],
    failure_markers: list[str],
) -> LogoutResult:
    text = _compact(response.text)
    text_casefold = text.casefold()

    for marker in failure_markers:
        compact_marker = _compact(marker).casefold()
        if compact_marker and compact_marker in text_casefold:
            return LogoutResult(False, f"Logout response contained failure marker: {marker}", response.status, response.url)

    for marker in success_markers:
        compact_marker = _compact(marker).casefold()
        if compact_marker and compact_marker in text_casefold:
            return LogoutResult(True, f"Logout response contained success marker: {marker}", response.status, response.url)

    if 200 <= response.status < 400:
        return LogoutResult(True, "Logout request completed.", response.status, response.url)

    return LogoutResult(False, f"Logout request failed with HTTP {response.status}", response.status, response.url)


def _derive_logout_url(login_url: str) -> str:
    parts = urllib.parse.urlsplit(login_url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    updated_query = []
    replaced_action = False
    for key, value in query:
        if key == "a" and value.lower() == "login":
            updated_query.append((key, "Logout"))
            replaced_action = True
        else:
            updated_query.append((key, value))
    if not replaced_action:
        updated_query.append(("a", "Logout"))
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urllib.parse.urlencode(updated_query),
            parts.fragment,
        )
    )


def _redact(value: str) -> str:
    if len(value) <= 2:
        return "***"
    return f"{value[:1]}***{value[-1:]}"


def _redact_url(url: str | None, extra_sensitive_keys: Iterable[str] = ()) -> str | None:
    if not url:
        return url
    parts = urllib.parse.urlsplit(url)
    sensitive_keys = {key.casefold() for key in SENSITIVE_QUERY_KEYS}
    sensitive_keys.update(key.casefold() for key in extra_sensitive_keys)
    query = []
    for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold() in sensitive_keys:
            query.append((key, "***"))
        else:
            query.append((key, value))
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urllib.parse.urlencode(query),
            parts.fragment,
        )
    )


def _mask_username(username: str) -> str:
    if len(username) <= 4:
        return "***"
    return f"{username[:2]}***{username[-2:]}"
