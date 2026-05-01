from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import AccountConfig, LoginConfig, require_secret


@dataclass(frozen=True)
class AccountCredentials:
    id: str
    username: str
    password: str
    username_env: str
    password_env: str


class AccountRegistry:
    def __init__(self, config: LoginConfig) -> None:
        self.config = config
        accounts = config.accounts or [AccountConfig("default", config.username_env, config.password_env)]
        self._accounts_by_id = {account.id: account for account in accounts}
        self._accounts = accounts
        self.state_path = Path(config.active_account_state_path)

    def list_accounts(self) -> list[AccountConfig]:
        return list(self._accounts)

    def current_account_config(self) -> AccountConfig:
        account_id = self.current_account_id()
        try:
            return self._accounts_by_id[account_id]
        except KeyError as exc:
            valid_ids = ", ".join(self._accounts_by_id)
            raise RuntimeError(f"Active account id {account_id!r} is not configured. Valid ids: {valid_ids}") from exc

    def current_account_id(self) -> str:
        state_id = self._read_state_account_id()
        if state_id:
            return state_id
        if self.config.active_account_id:
            return self.config.active_account_id
        return self._accounts[0].id

    def credentials(self, dry_run: bool = False) -> AccountCredentials:
        account = self.current_account_config()
        if dry_run:
            username = require_secret(account.username_env) if _env_has_value(account.username_env) else f"{account.id}-dry-run-user"
            password = require_secret(account.password_env) if _env_has_value(account.password_env) else "dry-run-password"
        else:
            username = require_secret(account.username_env)
            password = require_secret(account.password_env)
        return AccountCredentials(
            id=account.id,
            username=username,
            password=password,
            username_env=account.username_env,
            password_env=account.password_env,
        )

    def validate_secret_envs(self, account_id: str) -> None:
        account = self._account_by_id(account_id)
        require_secret(account.username_env)
        require_secret(account.password_env)

    def switch_to(self, account_id: str) -> AccountConfig:
        account = self._account_by_id(account_id)
        state = {
            "active_account_id": account.id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.state_path.parent != Path("."):
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return account

    def _account_by_id(self, account_id: str) -> AccountConfig:
        try:
            return self._accounts_by_id[account_id]
        except KeyError as exc:
            valid_ids = ", ".join(self._accounts_by_id)
            raise RuntimeError(f"Unknown account id {account_id!r}. Valid ids: {valid_ids}") from exc

    def _read_state_account_id(self) -> str | None:
        if not self.state_path.exists():
            return None
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read active account state {self.state_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise RuntimeError(f"Active account state must be a JSON object: {self.state_path}")
        account_id = raw.get("active_account_id")
        if account_id is None:
            return None
        return str(account_id)


def _env_has_value(name: str) -> bool:
    import os

    return bool(os.environ.get(name))
