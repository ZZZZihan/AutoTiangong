from __future__ import annotations

import random
import re
import urllib.parse
from dataclasses import dataclass


JS_ASSIGNMENT_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>'(?:\\'|[^'])*'|\"(?:\\\"|[^\"])*\"|-?\d+)"
)


@dataclass(frozen=True)
class DrcomPortalSettings:
    scheme: str
    host: str
    login_port: int = 801
    login_path: str = "/eportal/?c=ACSetting&a=Login"
    login_params: dict[str, str] | None = None
    username_field: str = "DDDDD"
    password_field: str = "upass"
    success_marker: str = "Dr.COMWebLoginID_3.htm"
    failure_marker: str = "Dr.COMWebLoginID_2.htm"
    charset: str = "gb2312"

    @property
    def login_url(self) -> str:
        netloc = f"{self.host}:{self.login_port}"
        parsed_path = urllib.parse.urlsplit(self.login_path)
        if parsed_path.scheme and parsed_path.netloc:
            return self.login_path
        path = parsed_path.path or "/"
        query = parsed_path.query
        return urllib.parse.urlunsplit((self.scheme, netloc, path, query, ""))


def parse_drcom_settings(portal_url: str, html: str) -> DrcomPortalSettings:
    parsed_url = urllib.parse.urlsplit(portal_url)
    assignments = _parse_js_assignments(html)
    login_params = dict(urllib.parse.parse_qsl(assignments.get("authloginparam", ""), keep_blank_values=True))
    login_port = _parse_int(assignments.get("authloginport"), parsed_url.port or 801)
    login_host = assignments.get("authloginIP") or parsed_url.hostname or parsed_url.netloc

    return DrcomPortalSettings(
        scheme=parsed_url.scheme or "http",
        host=login_host,
        login_port=login_port,
        login_path=assignments.get("authloginpath", "/eportal/?c=ACSetting&a=Login"),
        login_params=login_params,
        username_field=assignments.get("authuserfield", "DDDDD"),
        password_field=assignments.get("authpassfield", "upass"),
        success_marker=assignments.get("authsuccess", "Dr.COMWebLoginID_3.htm"),
        failure_marker=assignments.get("authfail", "Dr.COMWebLoginID_2.htm"),
        charset=assignments.get("charset", "gb2312"),
    )


def build_login_params(
    settings: DrcomPortalSettings,
    username: str,
    password: str,
    extra_fields: dict[str, str],
) -> dict[str, str]:
    params = dict(settings.login_params or {})
    params.update(extra_fields)
    params[settings.username_field] = username
    params[settings.password_field] = password
    params.setdefault("jsVersion", "4.X")
    params.setdefault("lang", "zh")
    params.setdefault("v", str(random.randint(500, 10499)))
    return params


def _parse_js_assignments(html: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for match in JS_ASSIGNMENT_RE.finditer(html):
        raw = match.group("value")
        assignments[match.group("name")] = _unquote_js_value(raw)
    return assignments


def _unquote_js_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] in {"'", '"'} and raw[-1] == raw[0]:
        return raw[1:-1].replace("\\'", "'").replace('\\"', '"')
    return raw


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default

