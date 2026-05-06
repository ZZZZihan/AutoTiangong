from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
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
        self.event_log_path = Path(config.account_event_log_path)
        self.unavailable_state_path = Path(config.auto_switch.unavailable_state_path)

    def list_accounts(self) -> list[AccountConfig]:
        return list(self._accounts)

    def account_configs_from_current(self) -> list[AccountConfig]:
        current_id = self.current_account_id()
        current_index = next(
            (index for index, account in enumerate(self._accounts) if account.id == current_id),
            None,
        )
        if current_index is None:
            valid_ids = ", ".join(self._accounts_by_id)
            raise RuntimeError(f"Active account id {current_id!r} is not configured. Valid ids: {valid_ids}")
        return [*self._accounts[current_index:], *self._accounts[:current_index]]

    def login_candidates(self, strategy: str = "round_robin") -> list[AccountConfig]:
        normalized_strategy = strategy.replace("-", "_").lower()
        if normalized_strategy == "round_robin":
            candidates = self.account_configs_from_current()
        elif normalized_strategy == "random":
            candidates = list(self._accounts)
            random.shuffle(candidates)
        else:
            raise RuntimeError(f"Unsupported account selection strategy: {strategy}")

        unavailable_ids = set(self.unavailable_accounts())
        return [account for account in candidates if account.id not in unavailable_ids]

    def unavailable_accounts(self) -> dict[str, dict[str, object]]:
        return self._load_unavailable_state()["accounts"]

    def is_unavailable(self, account_id: str) -> bool:
        self._account_by_id(account_id)
        return account_id in self.unavailable_accounts()

    def mark_unavailable(self, account_id: str, reason: str, reset_days: int = 1, source: str = "daemon") -> None:
        account = self._account_by_id(account_id)
        state = self._load_unavailable_state()
        entry: dict[str, object] = {
            "reason": reason,
            "marked_at": datetime.now(timezone.utc).isoformat(),
        }
        if reset_days > 0:
            entry["available_after"] = (date.today() + timedelta(days=reset_days)).isoformat()
        state["accounts"][account.id] = entry
        self._save_unavailable_state(state)
        self.record_event(
            "account_marked_unavailable",
            account_id=account.id,
            reason=reason,
            available_after=entry.get("available_after"),
            source=source,
        )

    def restore_account(self, account_id: str, source: str = "manual") -> bool:
        account = self._account_by_id(account_id)
        state = self._load_unavailable_state()
        existed = account.id in state["accounts"]
        if existed:
            del state["accounts"][account.id]
            self._save_unavailable_state(state)
            self.record_event("account_restored", account_id=account.id, source=source)
        return existed

    def restore_all_accounts(self, source: str = "manual") -> int:
        state = self._load_unavailable_state()
        restored_ids = sorted(state["accounts"])
        restored = len(state["accounts"])
        if restored:
            self._save_unavailable_state({"accounts": {}})
            self.record_event(
                "accounts_restored",
                account_ids=restored_ids,
                restored_count=restored,
                source=source,
            )
        return restored

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
        return self.credentials_for(self.current_account_id(), dry_run=dry_run)

    def credentials_for(self, account_id: str, dry_run: bool = False) -> AccountCredentials:
        account = self._account_by_id(account_id)
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

    def switch_to(self, account_id: str, source: str = "manual", reason: str = "manual_switch") -> AccountConfig:
        previous_account_id = self.current_account_id()
        account = self._account_by_id(account_id)
        self.restore_account(account.id, source=source)
        state = {
            "active_account_id": account.id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.state_path.parent != Path("."):
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        self.record_event(
            "active_account_switched",
            previous_account_id=previous_account_id,
            account_id=account.id,
            changed=previous_account_id != account.id,
            source=source,
            reason=reason,
        )
        return account

    def record_event(self, event: str, **fields: object) -> None:
        if self.event_log_path == Path("."):
            return
        entry: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        for key, value in fields.items():
            if value is not None:
                entry[key] = _event_value(value)
        if self.event_log_path.parent != Path("."):
            self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.event_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def account_events(self, limit: int | None = None, since: str | None = None) -> list[dict[str, object]]:
        if not self.event_log_path.exists():
            return []
        since_timestamp = _parse_event_timestamp(since) if since else None
        if since and since_timestamp is None:
            raise RuntimeError(f"Invalid event history timestamp: {since}")
        events = []
        for line in self.event_log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            timestamp = str(event.get("timestamp", ""))
            if since_timestamp is not None:
                event_timestamp = _parse_event_timestamp(timestamp)
                if event_timestamp is None or event_timestamp < since_timestamp:
                    continue
            elif since and timestamp < since:
                continue
            events.append(event)
        if limit is not None and limit > 0:
            return events[-limit:]
        return events

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

    def _load_unavailable_state(self) -> dict[str, dict[str, dict[str, object]]]:
        if not self.unavailable_state_path.exists():
            return {"accounts": {}}
        try:
            raw = json.loads(self.unavailable_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read unavailable account state {self.unavailable_state_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise RuntimeError(f"Unavailable account state must be a JSON object: {self.unavailable_state_path}")
        raw_accounts = raw.get("accounts", {})
        if not isinstance(raw_accounts, dict):
            raise RuntimeError(f"Unavailable account state accounts must be an object: {self.unavailable_state_path}")

        today = date.today().isoformat()
        changed = False
        accounts: dict[str, dict[str, object]] = {}
        for account_id, raw_entry in raw_accounts.items():
            if not isinstance(raw_entry, dict):
                changed = True
                continue
            available_after = raw_entry.get("available_after")
            if available_after is not None and str(available_after) <= today:
                changed = True
                continue
            if str(account_id) not in self._accounts_by_id:
                changed = True
                continue
            accounts[str(account_id)] = dict(raw_entry)

        state = {"accounts": accounts}
        if changed:
            self._save_unavailable_state(state)
        return state

    def _save_unavailable_state(self, state: dict[str, dict[str, dict[str, object]]]) -> None:
        if self.unavailable_state_path.parent != Path("."):
            self.unavailable_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.unavailable_state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _env_has_value(name: str) -> bool:
    import os

    return bool(os.environ.get(name))


def _event_value(value: object) -> object:
    if isinstance(value, str):
        return value if len(value) <= 1000 else f"{value[:997]}..."
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_event_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _event_value(item) for key, item in value.items()}
    return str(value)


def _parse_event_timestamp(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            parsed = datetime.combine(date.fromisoformat(text), time.min)
        else:
            parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)
