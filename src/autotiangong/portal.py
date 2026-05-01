from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
from dataclasses import dataclass

from .config import AppConfig
from .drcom import build_login_params, parse_drcom_settings
from .http_client import HttpClient, HttpResponse

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    message: str
    status: int | None = None
    url: str | None = None
    quota_limited: bool = False


@dataclass(frozen=True)
class LogoutResult:
    ok: bool
    message: str
    status: int | None = None
    url: str | None = None
    skipped: bool = False


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
            return LoginResult(True, f"Dry run prepared Dr.COM request to {login_url}", portal_response.status, login_url)

        response = self.http.submit(
            self.config.login.method,
            login_url,
            params,
            encoding=settings.charset,
            headers={"Referer": self.config.portal_url},
        )
        return _classify_login_response(response, self.config, settings.success_marker, settings.failure_marker)

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


def _classify_login_response(
    response: HttpResponse,
    config: AppConfig,
    portal_success_marker: str,
    portal_failure_marker: str,
) -> LoginResult:
    text = _compact(response.text)
    text_casefold = text.casefold()
    failure_markers = [portal_failure_marker, *config.login.failure_markers]
    success_markers = [portal_success_marker, *config.login.success_markers]

    for marker in config.login.quota_limit_markers:
        compact_marker = _compact(marker).casefold()
        if compact_marker and compact_marker in text_casefold:
            return LoginResult(
                False,
                f"Login response indicated account quota limit: {marker}",
                response.status,
                response.url,
                quota_limited=True,
            )

    for marker in failure_markers:
        if marker and marker in text:
            return LoginResult(False, f"Login response contained failure marker: {marker}", response.status, response.url)

    for marker in success_markers:
        if marker and marker in text:
            return LoginResult(True, f"Login response contained success marker: {marker}", response.status, response.url)

    if re.search(r"login_result['\"]?\s*:\s*[12]", text) or re.search(r"result['\"]?\s*:\s*1", text):
        return LoginResult(True, "Login response looked successful", response.status, response.url)

    if 200 <= response.status < 400:
        return LoginResult(False, "Login request completed but no success marker was found", response.status, response.url)

    return LoginResult(False, f"Login request failed with HTTP {response.status}", response.status, response.url)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


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


def _mask_username(username: str) -> str:
    if len(username) <= 4:
        return "***"
    return f"{username[:2]}***{username[-2:]}"
