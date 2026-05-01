from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from .config import load_config, load_env_file, require_secret
from .portal import CampusPortal


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    load_env_file(args.env_file)
    config = load_config(args.config)
    portal = CampusPortal(config)

    if args.interval is not None:
        interval = args.interval
    else:
        interval = config.check_interval_seconds

    while True:
        exit_code = _run_once(portal, config, args.dry_run)
        if args.once:
            return exit_code
        time.sleep(interval)


def _run_once(portal: CampusPortal, config, dry_run: bool) -> int:
    if portal.is_online():
        logging.info("Network is online; login not needed.")
        return 0

    logging.info("Connectivity check indicates captive/offline network; attempting login.")
    if dry_run:
        username = os.environ.get(config.login.username_env, "dry-run-user")
        password = os.environ.get(config.login.password_env, "dry-run-password")
    else:
        try:
            username = require_secret(config.login.username_env)
            password = require_secret(config.login.password_env)
        except RuntimeError as exc:
            logging.error("%s", exc)
            return 2

    result = portal.login(username, password, dry_run=dry_run)
    log_fn = logging.info if result.ok else logging.error
    log_fn("%s (status=%s url=%s)", result.message, result.status, result.url)
    return 0 if result.ok else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Authorized single-account Dr.COM auto-login demo.")
    parser.add_argument("--config", default=os.environ.get("AUTOTIANGONG_CONFIG", "config.local.json"))
    parser.add_argument("--env-file", default=os.environ.get("AUTOTIANGONG_ENV_FILE", ".env"))
    parser.add_argument("--once", action="store_true", help="Run one check/login cycle and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare the login request but do not submit it.")
    parser.add_argument("--interval", type=int, help="Override check interval in seconds.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
