from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from .accounts import AccountRegistry
from .config import load_config, load_env_file


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_env_file(args.env_file)
    config = load_config(args.config)
    registry = AccountRegistry(config.login)

    if args.history:
        try:
            events = registry.account_events(since=args.since if args.since and not args.today else None)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        if args.today:
            today = date.today().isoformat()
            events = [event for event in events if _local_event_date(event) == today]
        if args.history_limit > 0:
            events = events[-args.history_limit :]
        _print_history(events)
        return 0

    if args.list:
        current_id = registry.current_account_id()
        unavailable = registry.unavailable_accounts()
        for account in registry.list_accounts():
            marker = "*" if account.id == current_id else " "
            unavailable_note = ""
            if account.id in unavailable:
                reason = unavailable[account.id].get("reason", "unavailable")
                available_after = unavailable[account.id].get("available_after")
                reset_note = f"; available_after={available_after}" if available_after else ""
                unavailable_note = f" unavailable=1 reason={reason}{reset_note}"
            print(
                f"{marker} {account.id} username_env={account.username_env} "
                f"password_env={account.password_env}{unavailable_note}"
            )
        return 0

    if args.current:
        account = registry.current_account_config()
        unavailable_note = " unavailable=1" if registry.is_unavailable(account.id) else ""
        print(f"{account.id} username_env={account.username_env} password_env={account.password_env}{unavailable_note}")
        return 0

    if args.unavailable:
        unavailable = registry.unavailable_accounts()
        if not unavailable:
            print("No accounts are currently marked unavailable.")
            return 0
        for account_id, entry in sorted(unavailable.items()):
            reason = entry.get("reason", "unavailable")
            available_after = entry.get("available_after", "manual")
            print(f"{account_id} reason={reason} available_after={available_after}")
        return 0

    if args.restore_all:
        restored = registry.restore_all_accounts(source="manual_cli")
        print(f"Restored {restored} unavailable account marker(s).")
        return 0

    if args.restore:
        restored = registry.restore_account(args.restore, source="manual_cli")
        status = "restored" if restored else "was not marked unavailable"
        print(f"Account {args.restore} {status}.")
        return 0

    if args.to is None:
        raise SystemExit(
            "Specify --to ACCOUNT_ID, --restore ACCOUNT_ID, --restore-all, --unavailable, --history, --list, or --current."
        )

    if not args.no_secret_check:
        registry.validate_secret_envs(args.to)
    account = registry.switch_to(args.to, source="manual_cli", reason="manual_switch")
    print(f"Active account switched to {account.id}. Any unavailable marker for this account was cleared.")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manually select the active authorized lab account.")
    parser.add_argument("--config", default="config.local.json")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--to", help="Account id from login.accounts to select.")
    parser.add_argument("--restore", help="Clear the unavailable marker for one account id.")
    parser.add_argument("--restore-all", action="store_true", help="Clear all unavailable account markers.")
    parser.add_argument("--unavailable", action="store_true", help="List accounts currently marked unavailable.")
    parser.add_argument("--history", action="store_true", help="Show structured account login/switch event history.")
    parser.add_argument("--today", action="store_true", help="With --history, show only events recorded on the local date today.")
    parser.add_argument("--since", help="With --history, show events at or after this ISO date/timestamp.")
    parser.add_argument("--history-limit", type=int, default=50, help="Maximum history rows to show. Use 0 for all rows.")
    parser.add_argument("--list", action="store_true", help="List configured account ids.")
    parser.add_argument("--current", action="store_true", help="Show the active account id.")
    parser.add_argument(
        "--no-secret-check",
        action="store_true",
        help="Switch the account id without checking that its username/password environment variables are set.",
    )
    return parser.parse_args(argv)


def _print_history(events: list[dict[str, object]]) -> None:
    if not events:
        print("No account events recorded.")
        return
    switches = sum(1 for event in events if event.get("event") == "active_account_switched" and event.get("changed") is True)
    login_attempts = sum(1 for event in events if event.get("event") == "login_attempt")
    successful_logins = sum(1 for event in events if event.get("event") == "login_result" and event.get("ok") is True)
    print(
        f"Account events: total={len(events)} switches={switches} "
        f"login_attempts={login_attempts} successful_logins={successful_logins}"
    )
    for event in events:
        print(_format_event(event))


def _format_event(event: dict[str, object]) -> str:
    fields = [str(event.get("timestamp", "")), str(event.get("event", "event"))]
    for key in (
        "account_id",
        "previous_account_id",
        "changed",
        "source",
        "reason",
        "ok",
        "status",
        "available_after",
        "restored_count",
    ):
        if key in event:
            fields.append(f"{key}={event[key]}")
    return " ".join(field for field in fields if field)


def _local_event_date(event: dict[str, object]) -> str | None:
    timestamp = event.get("timestamp")
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(str(timestamp)).astimezone().date().isoformat()
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
