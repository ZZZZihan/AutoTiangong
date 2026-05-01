import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autotiangong.accounts import AccountRegistry
from autotiangong.config import AccountConfig, LoginConfig


class AccountRegistryTest(unittest.TestCase):
    def test_switches_active_account_without_storing_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            registry = AccountRegistry(
                LoginConfig(
                    active_account_state_path=str(state_path),
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

    def test_credentials_use_selected_account_environment_variables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            registry = AccountRegistry(
                LoginConfig(
                    active_account_state_path=str(state_path),
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


if __name__ == "__main__":
    unittest.main()
