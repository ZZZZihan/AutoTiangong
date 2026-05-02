import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from autotiangong.accounts import AccountRegistry
from autotiangong.config import AccountConfig, AppConfig, AutoSwitchConfig, LoginConfig
from autotiangong.daemon import TRAFFIC_LIMIT_EXIT_CODE, _run_once
from autotiangong.portal import LoginResult


class FakePortal:
    def __init__(self, config, results):
        self.config = config
        self.results = list(results)
        self.login_usernames = []
        self.online = False

    def is_online(self):
        return self.online

    def login(self, username, password, dry_run=False):
        self.login_usernames.append(username)
        return self.results.pop(0)


class FakeNotifier:
    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)
        return []


class DaemonAutoSwitchTest(unittest.TestCase):
    def test_auto_switch_tries_next_account_after_login_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            config = _config(state_path, auto_switch=AutoSwitchConfig(enabled=True))
            accounts = AccountRegistry(config.login)
            portal = FakePortal(
                config,
                [
                    LoginResult(False, "Login response contained failure marker: authfail", 200, "http://portal/login"),
                    LoginResult(True, "Login response contained success marker: ok", 200, "http://portal/login"),
                ],
            )

            with patch.dict(os.environ, {"USER_1": "alice", "PASS_1": "one", "USER_2": "bob", "PASS_2": "two"}):
                exit_code = _run_once(portal, config, False, accounts=accounts, notifier=FakeNotifier())

            self.assertEqual(exit_code, 0)
            self.assertEqual(portal.login_usernames, ["alice", "bob"])
            self.assertEqual(accounts.current_account_id(), "lab-secondary")

    def test_auto_switch_skips_accounts_with_missing_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            config = _config(state_path, auto_switch=AutoSwitchConfig(enabled=True))
            accounts = AccountRegistry(config.login)
            portal = FakePortal(
                config,
                [LoginResult(True, "Login response contained success marker: ok", 200, "http://portal/login")],
            )

            with patch.dict(os.environ, {"USER_2": "bob", "PASS_2": "two"}, clear=True):
                exit_code = _run_once(portal, config, False, accounts=accounts, notifier=FakeNotifier())

            self.assertEqual(exit_code, 0)
            self.assertEqual(portal.login_usernames, ["bob"])
            self.assertEqual(accounts.current_account_id(), "lab-secondary")

    def test_auto_switch_marks_quota_marker_unavailable_and_tries_next_account(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            config = _config(state_path, auto_switch=AutoSwitchConfig(enabled=True))
            accounts = AccountRegistry(config.login)
            notifier = FakeNotifier()
            portal = FakePortal(
                config,
                [
                    LoginResult(
                        False,
                        "Login response indicated account quota limit: quota limit",
                        200,
                        "http://portal/login",
                        quota_limited=True,
                    ),
                    LoginResult(True, "Should not be used", 200, "http://portal/login"),
                ],
            )

            with patch.dict(os.environ, {"USER_1": "alice", "PASS_1": "one", "USER_2": "bob", "PASS_2": "two"}):
                exit_code = _run_once(portal, config, False, accounts=accounts, notifier=notifier)

            self.assertEqual(exit_code, 0)
            self.assertEqual(portal.login_usernames, ["alice", "bob"])
            self.assertTrue(accounts.is_unavailable("lab-primary"))
            self.assertEqual(accounts.current_account_id(), "lab-secondary")
            self.assertEqual(notifier.events[0].account_id, "lab-primary")

    def test_auto_switch_skips_previously_marked_unavailable_accounts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            config = _config(state_path, auto_switch=AutoSwitchConfig(enabled=True))
            accounts = AccountRegistry(config.login)
            accounts.mark_unavailable("lab-primary", "password error")
            portal = FakePortal(
                config,
                [LoginResult(True, "Login response contained success marker: ok", 200, "http://portal/login")],
            )

            with patch.dict(os.environ, {"USER_1": "alice", "PASS_1": "one", "USER_2": "bob", "PASS_2": "two"}):
                exit_code = _run_once(portal, config, False, accounts=accounts, notifier=FakeNotifier())

            self.assertEqual(exit_code, 0)
            self.assertEqual(portal.login_usernames, ["bob"])

    def test_force_login_bypasses_online_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "active.json"
            config = _config(state_path, auto_switch=AutoSwitchConfig(enabled=False))
            accounts = AccountRegistry(config.login)
            portal = FakePortal(
                config,
                [LoginResult(True, "Login response contained success marker: ok", 200, "http://portal/login")],
            )
            portal.online = True

            with patch.dict(os.environ, {"USER_1": "alice", "PASS_1": "one"}, clear=True):
                exit_code = _run_once(
                    portal,
                    config,
                    False,
                    accounts=accounts,
                    notifier=FakeNotifier(),
                    force_login=True,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(portal.login_usernames, ["alice"])


def _config(state_path, auto_switch):
    auto_switch = replace(auto_switch, unavailable_state_path=str(Path(state_path).with_name("unavailable.json")))
    return AppConfig(
        portal_url="http://portal/",
        login=LoginConfig(
            active_account_id="lab-primary",
            active_account_state_path=str(state_path),
            accounts=[
                AccountConfig("lab-primary", "USER_1", "PASS_1"),
                AccountConfig("lab-secondary", "USER_2", "PASS_2"),
            ],
            auto_switch=auto_switch,
        ),
    )


if __name__ == "__main__":
    unittest.main()
