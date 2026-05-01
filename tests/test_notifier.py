import os
import unittest
from unittest.mock import patch

from autotiangong.config import WebhookConfig
from autotiangong.notifier import NotificationEvent, _webhook_payload


class NotifierTest(unittest.TestCase):
    def test_wecom_payload_uses_text_message_shape(self):
        payload = _webhook_payload(
            WebhookConfig(name="wecom", kind="wecom", url_env="WEBHOOK_URL"),
            NotificationEvent(
                title="Stopped",
                message="Traffic limit reached",
                account_id="lab-primary",
                account_label="la***ry",
                used_bytes=100,
                limit_bytes=200,
            ),
        )

        self.assertEqual(payload["msgtype"], "text")
        self.assertIn("Traffic limit reached", payload["text"]["content"])
        self.assertIn("account_id: lab-primary", payload["text"]["content"])

    def test_telegram_payload_reads_chat_id_from_environment(self):
        with patch.dict(os.environ, {"TELEGRAM_CHAT": "12345"}, clear=False):
            payload = _webhook_payload(
                WebhookConfig(name="telegram", kind="telegram", url_env="WEBHOOK_URL", chat_id_env="TELEGRAM_CHAT"),
                NotificationEvent(title="Stopped", message="Quota marker detected"),
            )

        self.assertEqual(payload["chat_id"], "12345")
        self.assertIn("Quota marker detected", payload["text"])


if __name__ == "__main__":
    unittest.main()
