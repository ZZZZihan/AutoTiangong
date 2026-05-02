from __future__ import annotations

import argparse
import sys

from .accounts import AccountRegistry
from .config import load_config, load_env_file


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_env_file(args.env_file)
    config = load_config(args.config)
    registry = AccountRegistry(config.login)

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
        restored = registry.restore_all_accounts()
        print(f"Restored {restored} unavailable account marker(s).")
        return 0

    if args.restore:
        restored = registry.restore_account(args.restore)
        status = "restored" if restored else "was not marked unavailable"
        print(f"Account {args.restore} {status}.")
        return 0

    if args.to is None:
        raise SystemExit("Specify --to ACCOUNT_ID, --restore ACCOUNT_ID, --restore-all, --unavailable, --list, or --current.")

    if not args.no_secret_check:
        registry.validate_secret_envs(args.to)
    account = registry.switch_to(args.to)
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
    parser.add_argument("--list", action="store_true", help="List configured account ids.")
    parser.add_argument("--current", action="store_true", help="Show the active account id.")
    parser.add_argument(
        "--no-secret-check",
        action="store_true",
        help="Switch the account id without checking that its username/password environment variables are set.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
