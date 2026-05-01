from __future__ import annotations

import logging
import re
import urllib.error
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


def _classify_login_response(
    response: HttpResponse,
    config: AppConfig,
    portal_success_marker: str,
    portal_failure_marker: str,
) -> LoginResult:
    text = _compact(response.text)
    failure_markers = [portal_failure_marker, *config.login.failure_markers]
    success_markers = [portal_success_marker, *config.login.success_markers]

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


def _redact(value: str) -> str:
    if len(value) <= 2:
        return "***"
    return f"{value[:1]}***{value[-1:]}"


def _mask_username(username: str) -> str:
    if len(username) <= 4:
        return "***"
    return f"{username[:2]}***{username[-2:]}"

