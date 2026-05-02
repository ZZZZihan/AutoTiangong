import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from autotiangong.accounts import AccountRegistry
from autotiangong.config import load_config
from autotiangong.switch_account import main


class SwitchAccountCliTest(unittest.TestCase):
    def test_restore_clears_unavailable_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _write_config(Path(tmpdir))
            registry = AccountRegistry(load_config(config_path).login)
            registry.mark_unavailable("lab-primary", "password error")

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--config", str(config_path), "--restore", "lab-primary"])

            self.assertEqual(exit_code, 0)
            self.assertIn("restored", output.getvalue())
            self.assertFalse(AccountRegistry(load_config(config_path).login).is_unavailable("lab-primary"))

    def test_manual_switch_clears_selected_account_unavailable_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _write_config(Path(tmpdir))
            registry = AccountRegistry(load_config(config_path).login)
            registry.mark_unavailable("lab-secondary", "会话异常")

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--config",
                        str(config_path),
                        "--to",
                        "lab-secondary",
                        "--no-secret-check",
                    ]
                )

            registry = AccountRegistry(load_config(config_path).login)
            self.assertEqual(exit_code, 0)
            self.assertIn("lab-secondary", output.getvalue())
            self.assertEqual(registry.current_account_id(), "lab-secondary")
            self.assertFalse(registry.is_unavailable("lab-secondary"))


def _write_config(tmpdir: Path) -> Path:
    config_path = tmpdir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "portal_url": "http://172.23.4.5/",
                "login": {
                    "active_account_id": "lab-primary",
                    "active_account_state_path": str(tmpdir / "active.json"),
                    "auto_switch": {
                        "unavailable_state_path": str(tmpdir / "unavailable.json"),
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
                },
            }
        ),
        encoding="utf-8",
    )
    return config_path


if __name__ == "__main__":
    unittest.main()
