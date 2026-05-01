# AutoTiangong

Authorized single-account campus portal auto-login demo for a lab gateway or a personal machine.

This project intentionally does **not** implement multi-account rotation or quota bypass. It reads one authorized account from environment variables, checks whether the network is already online, and only attempts login when the connectivity check looks captive or offline.

## What it does

- Detects captive portal status with an HTTP connectivity endpoint.
- Parses Dr.COM portal settings from the landing page when available.
- Sends a configurable Dr.COM login request with one authorized account.
- Runs once for testing or continuously as a small background loop.
- Keeps credentials out of code, config, logs, commits, and examples.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
cp config.example.json config.local.json
```

Edit `.env` locally:

```bash
CAMPUS_NET_USERNAME=your_authorized_lab_or_personal_account
CAMPUS_NET_PASSWORD=your_password
```

Run a safe dry run:

```bash
python -m autotiangong --config config.local.json --once --dry-run
```

Run one real login attempt if the connectivity check fails:

```bash
python -m autotiangong --config config.local.json --once
```

Run as a foreground loop:

```bash
python -m autotiangong --config config.local.json
```

## Configuration

`config.example.json` is set up for the observed Dr.COM portal at `http://172.23.4.5/`. If the school changes its portal, keep secrets in `.env` and adjust only the non-secret fields in `config.local.json`.

Important fields:

- `portal_url`: captive portal landing page.
- `connectivity_url`: plain HTTP URL that should return a known status when fully online.
- `connectivity_expected_status`: expected status for `connectivity_url`; `204` is common.
- `login.extra_fields`: non-secret Dr.COM parameters.
- `login.username_env` and `login.password_env`: environment variable names used for secrets.

## Tests

```bash
python -m unittest discover -s tests
```

## Safety notes

- Use only accounts you are authorized to automate.
- Do not commit `.env`, `config.local.json`, or logs.
- If a password was pasted into a chat, shell history, or log, rotate it.
- For a shared lab, prefer an official lab/service account from the network office.

