from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import replace

from .accounts import AccountCredentials, AccountRegistry
from .config import AccountConfig, AppConfig, AutoSwitchConfig, load_config, load_env_file
from .notifier import NotificationEvent, Notifier
from .portal import CampusPortal
from .traffic import TrafficGuard

TRAFFIC_LIMIT_EXIT_CODE = 3


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    load_env_file(args.env_file)
    config = _apply_cli_overrides(load_config(args.config), args)
    portal = CampusPortal(config)
    accounts = AccountRegistry(config.login)
    traffic_guard = TrafficGuard(config.traffic_guard)
    notifier = Notifier(config.notifications)

    if args.interval is not None:
        interval = args.interval
    else:
        interval = config.check_interval_seconds

    while True:
        exit_code = _run_once(portal, config, args.dry_run, traffic_guard, accounts, notifier, force_login=args.force_login)
        if args.once or exit_code == TRAFFIC_LIMIT_EXIT_CODE:
            return exit_code
        time.sleep(interval)


def _run_once(
    portal: CampusPortal,
    config: AppConfig,
    dry_run: bool,
    traffic_guard: TrafficGuard | None = None,
    accounts: AccountRegistry | None = None,
    notifier: Notifier | None = None,
    force_login: bool = False,
) -> int:
    accounts = accounts or AccountRegistry(config.login)
    notifier = notifier or Notifier(config.notifications)

    if traffic_guard and traffic_guard.enabled:
        status = traffic_guard.check()
        log_fn = logging.info if status.ok else logging.error
        log_fn("%s", status.message)
        if not status.ok:
            return _stop_for_limit(
                portal,
                accounts,
                notifier,
                dry_run,
                "AutoTiangong stopped by traffic guard",
                status.message,
                account_label=status.account_label,
                used_bytes=status.used_bytes,
                limit_bytes=status.limit_bytes,
            )

    if not force_login and portal.is_online():
        logging.info("Network is online; login not needed.")
        return 0

    if force_login:
        logging.info("Force login requested; attempting login even though connectivity may already be online.")
    else:
        logging.info("Connectivity check indicates captive/offline network; attempting login.")
    try:
        candidates = _login_candidates(accounts, config.login.auto_switch)
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 2

    credentials_error_count = 0
    for index, account in enumerate(candidates):
        try:
            credentials = accounts.credentials_for(account.id, dry_run=dry_run)
        except RuntimeError as exc:
            credentials_error_count += 1
            logging.error("%s", exc)
            if not config.login.auto_switch.enabled:
                return 2
            continue

        logging.info("Using authorized account id: %s", credentials.id)
        result = portal.login(credentials.username, credentials.password, dry_run=dry_run)
        log_fn = logging.info if result.ok else logging.error
        log_fn("%s (reason=%s status=%s url=%s)", result.message, result.reason, result.status, result.url)
        if result.ok:
            if _should_persist_auto_switch(accounts, credentials, config, dry_run):
                accounts.switch_to(credentials.id)
                logging.info("Active account switched to %s after successful automatic login.", credentials.id)
            if traffic_guard and traffic_guard.enabled and not dry_run:
                status = traffic_guard.activate(credentials.username)
                log_fn = logging.info if status.ok else logging.error
                log_fn("%s", status.message)
                if not status.ok:
                    return _stop_for_limit(
                        portal,
                        accounts,
                        notifier,
                        dry_run,
                        "AutoTiangong stopped by traffic guard",
                        status.message,
                        credentials=credentials,
                        account_label=status.account_label,
                        used_bytes=status.used_bytes,
                        limit_bytes=status.limit_bytes,
                    )
            return 0

        account_unavailable = result.account_unavailable or result.quota_limited
        if account_unavailable:
            if not dry_run:
                accounts.mark_unavailable(
                    credentials.id,
                    result.message,
                    reset_days=config.login.auto_switch.unavailable_reset_days,
                )
            logging.warning(
                "Account id %s marked unavailable%s.",
                credentials.id,
                " for this rotation window" if config.login.auto_switch.unavailable_reset_days else "",
            )
            _notify_account_unavailable(notifier, credentials, result.message)

        if config.login.auto_switch.enabled and index < len(candidates) - 1:
            if account_unavailable:
                logging.info("Trying next available authorized account after unavailable marker.")
            else:
                logging.info("Login failed for account id %s; trying next authorized account.", credentials.id)

    if credentials_error_count == len(candidates):
        return 2
    return 1


def _login_candidates(accounts: AccountRegistry, auto_switch: AutoSwitchConfig) -> list[AccountConfig]:
    if auto_switch.enabled:
        candidates = accounts.login_candidates(auto_switch.strategy)
        if not candidates:
            raise RuntimeError("No configured accounts are currently available for automatic switching.")
        return candidates
    return [accounts.current_account_config()]


def _should_persist_auto_switch(
    accounts: AccountRegistry,
    credentials: AccountCredentials,
    config: AppConfig,
    dry_run: bool,
) -> bool:
    return (
        config.login.auto_switch.enabled
        and config.login.auto_switch.persist_success
        and not dry_run
        and credentials.id != accounts.current_account_id()
    )


def _stop_for_limit(
    portal: CampusPortal,
    accounts: AccountRegistry,
    notifier: Notifier,
    dry_run: bool,
    title: str,
    message: str,
    credentials: AccountCredentials | None = None,
    account_label: str | None = None,
    used_bytes: int | None = None,
    limit_bytes: int | None = None,
) -> int:
    if credentials is None:
        try:
            credentials = accounts.credentials(dry_run=dry_run)
        except RuntimeError as exc:
            logging.error("Could not load active account credentials for logout: %s", exc)

    account_id = credentials.id if credentials else accounts.current_account_id()
    if credentials is not None and portal.config.logout.enabled:
        logout_result = portal.logout(credentials.username, dry_run=dry_run)
        log_fn = logging.info if logout_result.ok else logging.error
        log_fn("%s (status=%s url=%s)", logout_result.message, logout_result.status, logout_result.url)

    event = NotificationEvent(
        title=title,
        message=message,
        account_id=account_id,
        account_label=account_label,
        used_bytes=used_bytes,
        limit_bytes=limit_bytes,
    )
    for result in notifier.send(event):
        log_fn = logging.info if result.ok else logging.error
        log_fn("Notification %s: %s", result.target, result.message)
    return TRAFFIC_LIMIT_EXIT_CODE


def _notify_account_unavailable(notifier: Notifier, credentials: AccountCredentials, message: str) -> None:
    event = NotificationEvent(
        title="AutoTiangong marked account unavailable",
        message=message,
        account_id=credentials.id,
    )
    for result in notifier.send(event):
        log_fn = logging.info if result.ok else logging.error
        log_fn("Notification %s: %s", result.target, result.message)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Authorized Dr.COM campus portal guard.")
    parser.add_argument("--config", default=os.environ.get("AUTOTIANGONG_CONFIG", "config.local.json"))
    parser.add_argument("--env-file", default=os.environ.get("AUTOTIANGONG_ENV_FILE", ".env"))
    parser.add_argument("--once", action="store_true", help="Run one check/login cycle and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare the login request but do not submit it.")
    parser.add_argument("--force-login", action="store_true", help="Attempt login even when the connectivity check is online.")
    parser.add_argument("--interval", type=int, help="Override check interval in seconds.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    auto_switch = parser.add_mutually_exclusive_group()
    auto_switch.add_argument(
        "--auto-switch",
        action="store_true",
        dest="auto_switch",
        default=None,
        help="Temporarily enable automatic failover between configured accounts.",
    )
    auto_switch.add_argument(
        "--no-auto-switch",
        action="store_false",
        dest="auto_switch",
        help="Temporarily disable automatic failover between configured accounts.",
    )
    return parser.parse_args(argv)


def _apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    if args.auto_switch is None:
        return config
    auto_switch = replace(config.login.auto_switch, enabled=args.auto_switch)
    return replace(config, login=replace(config.login, auto_switch=auto_switch))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
