import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autotiangong.config import load_config


class ConfigTest(unittest.TestCase):
    def test_loads_traffic_guard_and_quota_markers(self):
        raw_config = {
            "portal_url": "http://172.23.4.5/",
            "login": {
                "active_account_id": "lab-primary",
                "active_account_state_path": "state/active.json",
                "kernel_port": 9002,
                "fallback_to_kernel": True,
                "auto_switch": {
                    "enabled": True,
                    "persist_success": False,
                    "strategy": "random",
                    "unavailable_state_path": "state/unavailable.json",
                    "unavailable_reset_days": 2,
                },
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
                "account_unavailable_markers": ["账号不可用", "password error"],
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
        self.assertEqual(config.login.kernel_port, 9002)
        self.assertTrue(config.login.fallback_to_kernel)
        self.assertTrue(config.login.auto_switch.enabled)
        self.assertFalse(config.login.auto_switch.persist_success)
        self.assertEqual(config.login.auto_switch.strategy, "random")
        self.assertEqual(config.login.auto_switch.unavailable_state_path, "state/unavailable.json")
        self.assertEqual(config.login.auto_switch.unavailable_reset_days, 2)
        self.assertEqual([account.id for account in config.login.accounts], ["lab-primary", "lab-secondary"])
        self.assertEqual(config.login.quota_limit_markers, ["流量已达上限"])
        self.assertEqual(config.login.account_unavailable_markers, ["账号不可用", "password error"])
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

    def test_loads_yaml_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            path.write_text(
                """
portal_url: http://172.23.4.5/
login:
  active_account_id: lab-primary
  auto_switch:
    enabled: true
    strategy: round-robin
  accounts:
    - id: lab-primary
      username_env: USER_1
      password_env: PASS_1
""".strip(),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.portal_url, "http://172.23.4.5/")
        self.assertTrue(config.login.auto_switch.enabled)
        self.assertEqual(config.login.auto_switch.strategy, "round_robin")
        self.assertIn("账号不可用", config.login.account_unavailable_markers)

    def test_discovers_numbered_accounts_from_loaded_environment(self):
        raw_config = {
            "portal_url": "http://172.23.4.5/",
            "login": {
                "active_account_id": "lab-primary",
                "username_env": "CAMPUS_NET_USERNAME",
                "password_env": "CAMPUS_NET_PASSWORD",
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps(raw_config), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "CAMPUS_NET_USERNAME_2": "secondary-user",
                    "CAMPUS_NET_PASSWORD_2": "secondary-password",
                },
                clear=True,
            ):
                config = load_config(path)

        self.assertEqual([account.id for account in config.login.accounts], ["lab-primary", "lab-primary-2"])


if __name__ == "__main__":
    unittest.main()
