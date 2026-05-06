import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from autotiangong.accounts import AccountRegistry
from autotiangong.config import AccountConfig, AutoSwitchConfig, LoginConfig


class AccountRegistryTest(unittest.TestCase):
    def test_switches_active_account_without_storing_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            registry = AccountRegistry(
                LoginConfig(
                    active_account_state_path=str(state_path),
                    account_event_log_path=str(Path(tmpdir) / "events.jsonl"),
                    accounts=[
                        AccountConfig("lab-primary", "USER_1", "PASS_1"),
                        AccountConfig("lab-secondary", "USER_2", "PASS_2"),
                    ],
                )
            )

            self.assertEqual(registry.current_account_id(), "lab-primary")
            registry.switch_to("lab-secondary")
            self.assertEqual(registry.current_account_id(), "lab-secondary")

            raw_state = state_path.read_text(encoding="utf-8")
            self.assertIn("lab-secondary", raw_state)
            self.assertNotIn("USER_2", raw_state)
            self.assertNotIn("PASS_2", raw_state)
            raw_events = (Path(tmpdir) / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("active_account_switched", raw_events)
            self.assertIn("lab-secondary", raw_events)
            self.assertNotIn("USER_2", raw_events)
            self.assertNotIn("PASS_2", raw_events)

    def test_credentials_use_selected_account_environment_variables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            registry = AccountRegistry(
                LoginConfig(
                    active_account_state_path=str(state_path),
                    account_event_log_path=str(Path(tmpdir) / "events.jsonl"),
                    accounts=[
                        AccountConfig("lab-primary", "USER_1", "PASS_1"),
                        AccountConfig("lab-secondary", "USER_2", "PASS_2"),
                    ],
                )
            )
            registry.switch_to("lab-secondary")

            with patch.dict(os.environ, {"USER_2": "alice", "PASS_2": "secret"}, clear=False):
                credentials = registry.credentials()

        self.assertEqual(credentials.id, "lab-secondary")
        self.assertEqual(credentials.username, "alice")
        self.assertEqual(credentials.password, "secret")

    def test_account_candidates_start_from_current_account(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            registry = AccountRegistry(
                LoginConfig(
                    active_account_state_path=str(state_path),
                    account_event_log_path=str(Path(tmpdir) / "events.jsonl"),
                    accounts=[
                        AccountConfig("lab-primary", "USER_1", "PASS_1"),
                        AccountConfig("lab-secondary", "USER_2", "PASS_2"),
                        AccountConfig("lab-tertiary", "USER_3", "PASS_3"),
                    ],
                )
            )
            registry.switch_to("lab-secondary")

            ordered_ids = [account.id for account in registry.account_configs_from_current()]

        self.assertEqual(ordered_ids, ["lab-secondary", "lab-tertiary", "lab-primary"])

    def test_login_candidates_skip_marked_unavailable_accounts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            unavailable_path = Path(tmpdir) / "unavailable.json"
            registry = AccountRegistry(
                LoginConfig(
                    active_account_state_path=str(state_path),
                    account_event_log_path=str(Path(tmpdir) / "events.jsonl"),
                    auto_switch=AutoSwitchConfig(unavailable_state_path=str(unavailable_path)),
                    accounts=[
                        AccountConfig("lab-primary", "USER_1", "PASS_1"),
                        AccountConfig("lab-secondary", "USER_2", "PASS_2"),
                    ],
                )
            )

            registry.mark_unavailable("lab-primary", "password error", reset_days=1)
            candidates = [account.id for account in registry.login_candidates()]

            self.assertEqual(candidates, ["lab-secondary"])
            raw_state = unavailable_path.read_text(encoding="utf-8")
            self.assertIn("password error", raw_state)
            self.assertNotIn("USER_1", raw_state)
            self.assertNotIn("PASS_1", raw_state)

            self.assertTrue(registry.restore_account("lab-primary"))
            self.assertEqual([account.id for account in registry.login_candidates()], ["lab-primary", "lab-secondary"])

    def test_unavailable_marker_expires_after_available_after_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            unavailable_path = Path(tmpdir) / "unavailable.json"
            unavailable_path.write_text(
                json.dumps(
                    {
                        "accounts": {
                            "lab-primary": {
                                "reason": "流量已用尽",
                                "marked_at": "2026-01-01T00:00:00+00:00",
                                "available_after": (date.today() - timedelta(days=1)).isoformat(),
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            registry = AccountRegistry(
                LoginConfig(
                    active_account_state_path=str(Path(tmpdir) / "active.json"),
                    account_event_log_path=str(Path(tmpdir) / "events.jsonl"),
                    auto_switch=AutoSwitchConfig(unavailable_state_path=str(unavailable_path)),
                    accounts=[
                        AccountConfig("lab-primary", "USER_1", "PASS_1"),
                        AccountConfig("lab-secondary", "USER_2", "PASS_2"),
                    ],
                )
            )

            self.assertFalse(registry.is_unavailable("lab-primary"))
            self.assertEqual(registry.unavailable_accounts(), {})

    def test_account_events_since_compares_offset_timestamps_by_instant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_log_path = Path(tmpdir) / "events.jsonl"
            event_log_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-05-04T15:30:00+00:00",
                                "event": "active_account_switched",
                                "account_id": "lab-primary",
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-05-04T16:30:00+00:00",
                                "event": "active_account_switched",
                                "account_id": "lab-secondary",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            registry = AccountRegistry(
                LoginConfig(
                    active_account_state_path=str(Path(tmpdir) / "active.json"),
                    account_event_log_path=str(event_log_path),
                    accounts=[
                        AccountConfig("lab-primary", "USER_1", "PASS_1"),
                        AccountConfig("lab-secondary", "USER_2", "PASS_2"),
                    ],
                )
            )

            events = registry.account_events(since="2026-05-05T00:00:00+08:00")

            self.assertEqual([event["account_id"] for event in events], ["lab-secondary"])


if __name__ == "__main__":
    unittest.main()
