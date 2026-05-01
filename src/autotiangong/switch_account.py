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
        for account in registry.list_accounts():
            marker = "*" if account.id == current_id else " "
            print(f"{marker} {account.id} username_env={account.username_env} password_env={account.password_env}")
        return 0

    if args.current:
        account = registry.current_account_config()
        print(f"{account.id} username_env={account.username_env} password_env={account.password_env}")
        return 0

    if args.to is None:
        raise SystemExit("Specify --to ACCOUNT_ID, --list, or --current.")

    if not args.no_secret_check:
        registry.validate_secret_envs(args.to)
    account = registry.switch_to(args.to)
    print(f"Active account switched to {account.id}. Restart the daemon to use it immediately.")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manually select the active authorized lab account.")
    parser.add_argument("--config", default="config.local.json")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--to", help="Account id from login.accounts to select.")
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
