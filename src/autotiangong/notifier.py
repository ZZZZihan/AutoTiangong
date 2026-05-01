from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage

from .config import EmailConfig, NotificationConfig, WebhookConfig
from .traffic import format_bytes


@dataclass(frozen=True)
class NotificationEvent:
    title: str
    message: str
    level: str = "warning"
    account_id: str | None = None
    account_label: str | None = None
    used_bytes: int | None = None
    limit_bytes: int | None = None


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    target: str
    message: str


class Notifier:
    def __init__(self, config: NotificationConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def send(self, event: NotificationEvent) -> list[DeliveryResult]:
        if not self.enabled:
            return []

        results = []
        for webhook in self.config.webhooks:
            results.append(_send_webhook(webhook, event))
        if self.config.email.enabled:
            results.append(_send_email(self.config.email, event))
        return results


def _send_webhook(config: WebhookConfig, event: NotificationEvent) -> DeliveryResult:
    try:
        url = _webhook_url(config)
        payload = _webhook_payload(config, event)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "AutoTiangong/0.1",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            if 200 <= response.status < 300:
                return DeliveryResult(True, config.name, f"Webhook delivered with HTTP {response.status}.")
            return DeliveryResult(False, config.name, f"Webhook returned HTTP {response.status}.")
    except Exception as exc:  # noqa: BLE001 - notification failures should not hide the root event.
        return DeliveryResult(False, config.name, f"Webhook delivery failed: {exc}")


def _send_email(config: EmailConfig, event: NotificationEvent) -> DeliveryResult:
    try:
        host = _required_env(config.smtp_host_env)
        sender = _required_env(config.from_env)
        recipients = _split_recipients(_required_env(config.to_env))

        message = EmailMessage()
        message["Subject"] = event.title
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message.set_content(_event_text(event))

        with smtplib.SMTP(host, config.smtp_port, timeout=10) as smtp:
            if config.use_tls:
                smtp.starttls()
            if config.username_env and config.password_env:
                username = os.environ.get(config.username_env)
                password = os.environ.get(config.password_env)
                if username and password:
                    smtp.login(username, password)
            smtp.send_message(message)
        return DeliveryResult(True, "email", "Email delivered.")
    except Exception as exc:  # noqa: BLE001 - notification failures should not hide the root event.
        return DeliveryResult(False, "email", f"Email delivery failed: {exc}")


def _webhook_url(config: WebhookConfig) -> str:
    if config.url:
        return config.url
    if config.url_env:
        return _required_env(config.url_env)
    raise RuntimeError(f"Webhook {config.name} does not define url or url_env")


def _webhook_payload(config: WebhookConfig, event: NotificationEvent) -> dict[str, object]:
    text = _event_text(event)
    if config.kind in {"wecom", "wechat-work", "dingtalk"}:
        return {"msgtype": "text", "text": {"content": text}}
    if config.kind == "telegram":
        if not config.chat_id_env:
            raise RuntimeError(f"Telegram webhook {config.name} must define chat_id_env")
        return {"chat_id": _required_env(config.chat_id_env), "text": text}
    return {
        "title": event.title,
        "message": event.message,
        "level": event.level,
        "account_id": event.account_id,
        "account_label": event.account_label,
        "used_bytes": event.used_bytes,
        "limit_bytes": event.limit_bytes,
    }


def _event_text(event: NotificationEvent) -> str:
    lines = [event.title, event.message]
    if event.account_id:
        lines.append(f"account_id: {event.account_id}")
    if event.account_label:
        lines.append(f"account: {event.account_label}")
    if event.used_bytes is not None and event.limit_bytes is not None:
        lines.append(f"usage: {format_bytes(event.used_bytes)} / {format_bytes(event.limit_bytes)}")
    return "\n".join(lines)


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _split_recipients(value: str) -> list[str]:
    recipients = [item.strip() for item in value.replace(";", ",").split(",")]
    return [item for item in recipients if item]
