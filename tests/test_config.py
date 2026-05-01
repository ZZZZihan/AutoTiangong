import json
import tempfile
import unittest
from pathlib import Path

from autotiangong.config import load_config


class ConfigTest(unittest.TestCase):
    def test_loads_traffic_guard_and_quota_markers(self):
        raw_config = {
            "portal_url": "http://172.23.4.5/",
            "login": {
                "active_account_id": "lab-primary",
                "active_account_state_path": "state/active.json",
                "accounts": [
                    {
                        "id": "lab-primary",
                        "username_env": "USER_1",
                        "password_env": "PASS_1",
                    },
                    {
                        "id": "lab-secondary",
                        "username_env": "USER_2",
                        "password_env": "PASS_2",
                    },
                ],
                "quota_limit_markers": ["流量已达上限"],
            },
            "logout": {
                "enabled": True,
                "url": "http://172.23.4.5:801/eportal/?c=ACSetting&a=Logout",
                "extra_fields": {"keep": "1"},
                "success_markers": ["logout ok"],
            },
            "notifications": {
                "enabled": True,
                "webhooks": [
                    {
                        "name": "wecom",
                        "kind": "wecom",
                        "url_env": "WEBHOOK_URL",
                    }
                ],
                "email": {
                    "enabled": True,
                    "smtp_host_env": "SMTP_HOST",
                    "to_env": "EMAIL_TO",
                },
            },
            "traffic_guard": {
                "enabled": True,
                "limit_gib": 4.9,
                "state_path": "state/traffic.json",
                "interface": "Ethernet",
                "fail_closed": False,
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps(raw_config), encoding="utf-8")

            config = load_config(path)

        self.assertTrue(config.traffic_guard.enabled)
        self.assertEqual(config.traffic_guard.limit_bytes, int(4.9 * 1024 * 1024 * 1024))
        self.assertEqual(config.traffic_guard.state_path, "state/traffic.json")
        self.assertEqual(config.traffic_guard.interface, "Ethernet")
        self.assertFalse(config.traffic_guard.fail_closed)
        self.assertEqual(config.login.active_account_id, "lab-primary")
        self.assertEqual(config.login.active_account_state_path, "state/active.json")
        self.assertEqual([account.id for account in config.login.accounts], ["lab-primary", "lab-secondary"])
        self.assertEqual(config.login.quota_limit_markers, ["流量已达上限"])
        self.assertTrue(config.logout.enabled)
        self.assertEqual(config.logout.extra_fields, {"keep": "1"})
        self.assertTrue(config.notifications.enabled)
        self.assertEqual(config.notifications.webhooks[0].kind, "wecom")
        self.assertTrue(config.notifications.email.enabled)

    def test_rejects_unknown_active_account_id(self):
        raw_config = {
            "portal_url": "http://172.23.4.5/",
            "login": {
                "active_account_id": "missing",
                "accounts": [
                    {
                        "id": "lab-primary",
                        "username_env": "USER_1",
                        "password_env": "PASS_1",
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps(raw_config), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
