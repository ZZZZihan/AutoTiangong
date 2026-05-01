from __future__ import annotations

import http.cookiejar
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import Message


@dataclass(frozen=True)
class HttpResponse:
    status: int
    url: str
    body: bytes
    headers: Message

    @property
    def text(self) -> str:
        charset = _charset_from_headers(self.headers) or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class HttpClient:
    def __init__(self, timeout_seconds: int = 8) -> None:
        self.timeout_seconds = timeout_seconds
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        return self.request("GET", url, headers=headers)

    def submit(
        self,
        method: str,
        url: str,
        params: dict[str, str],
        encoding: str = "utf-8",
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        method = method.upper()
        if method == "GET":
            separator = "&" if urllib.parse.urlsplit(url).query else "?"
            query = urllib.parse.urlencode(params, encoding=encoding, errors="replace")
            return self.request("GET", f"{url}{separator}{query}", headers=headers)

        body = urllib.parse.urlencode(params, encoding=encoding, errors="replace").encode("ascii")
        merged_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if headers:
            merged_headers.update(headers)
        return self.request(method, url, body=body, headers=merged_headers)

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        request_headers = {
            "User-Agent": "AutoTiangong/0.1 (+authorized auto-login demo)",
            "Accept": "text/html,application/json,text/javascript,*/*;q=0.8",
        }
        if headers:
            request_headers.update(headers)

        request = urllib.request.Request(url, data=body, headers=request_headers, method=method.upper())
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                return HttpResponse(
                    status=response.status,
                    url=response.geturl(),
                    body=response.read(),
                    headers=response.headers,
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(
                status=exc.code,
                url=exc.geturl(),
                body=exc.read(),
                headers=exc.headers,
            )


def _charset_from_headers(headers: Message) -> str | None:
    content_type = headers.get("Content-Type", "")
    match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip('"')

