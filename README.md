# AutoTiangong

Authorized campus portal guard for a lab gateway or a personal machine.

This project intentionally does **not** implement unattended multi-account rotation or quota bypass. It can register multiple lab-authorized accounts, but the daemon only uses the administrator-selected active account. When traffic guardrails or quota-limit portal messages are hit, it stops, optionally logs out, and notifies administrators for manual intervention.

## What it does

- Detects captive portal status with an HTTP connectivity endpoint.
- Parses Dr.COM portal settings from the landing page when available.
- Sends a configurable Dr.COM login request with the administrator-selected authorized account.
- Supports a local registry of multiple authorized lab accounts without storing passwords in config or state.
- Provides a manual account switch command for administrators.
- Can stop automatically when local traffic for the current login session reaches a configured guardrail such as 4.9 GiB.
- Can treat configured portal response text as an account quota-limit warning, optionally log out, notify admins, and stop instead of retrying.
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
CAMPUS_NET_USERNAME_2=another_authorized_lab_account
CAMPUS_NET_PASSWORD_2=another_password
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

List configured accounts:

```bash
python -m autotiangong.switch_account --config config.local.json --list
```

Manually switch the active account after administrator approval:

```bash
python -m autotiangong.switch_account --config config.local.json --to lab-secondary
```

## Configuration

`config.example.json` is set up for the observed Dr.COM portal at `http://172.23.4.5/`. If the school changes its portal, keep secrets in `.env` and adjust only the non-secret fields in `config.local.json`.

Important fields:

- `portal_url`: captive portal landing page.
- `connectivity_url`: plain HTTP URL that should return a known status when fully online.
- `connectivity_expected_status`: expected status for `connectivity_url`; `204` is common.
- `login.accounts`: authorized lab account IDs and their username/password environment variable names.
- `login.active_account_id`: default account ID when no manual switch state exists.
- `login.active_account_state_path`: local state file used by the manual switch command.
- `login.extra_fields`: non-secret Dr.COM parameters.
- `login.username_env` and `login.password_env`: environment variable names used for secrets.
- `login.quota_limit_markers`: response text snippets that mean the portal says the account has reached its quota.
- `logout.enabled`: enables best-effort logout when the daemon stops for a quota or traffic guardrail.
- `notifications.enabled`: enables webhook/email admin notifications when the daemon stops for a quota or traffic guardrail.
- `traffic_guard.enabled`: enables local traffic tracking for the current login session.
- `traffic_guard.limit_gib`: local usage guardrail; `4.9` means 4.9 GiB.
- `traffic_guard.interface`: optional network interface/adapter name. On Windows this is matched against the adapter name reported by `Get-CimInstance Win32_PerfRawData_Tcpip_NetworkInterface`.
- `traffic_guard.fail_closed`: when true, a counter read failure stops automatic login.

The traffic guard reads host-level adapter counters, so traffic from other processes on the same machine can count toward the guardrail. It records only a masked account label, a username hash, byte counters, and timestamps in `traffic_guard.state_path`. The manual switch command records only the active account ID and timestamp in `login.active_account_state_path`. Neither state file stores passwords.

Register multiple lab-authorized accounts in `config.local.json`:

```json
{
  "login": {
    "active_account_id": "lab-primary",
    "active_account_state_path": ".autotiangong-active-account.json",
    "accounts": [
      {
        "id": "lab-primary",
        "username_env": "CAMPUS_NET_USERNAME",
        "password_env": "CAMPUS_NET_PASSWORD"
      },
      {
        "id": "lab-secondary",
        "username_env": "CAMPUS_NET_USERNAME_2",
        "password_env": "CAMPUS_NET_PASSWORD_2"
      }
    ]
  }
}
```

Add or update a 4.9 GiB guardrail in `config.local.json`:

```json
{
  "traffic_guard": {
    "enabled": true,
    "limit_gib": 4.9,
    "state_path": ".autotiangong-traffic.json",
    "interface": null,
    "fail_closed": true
  }
}
```

When the guardrail is reached, or when a configured quota-limit marker appears in the portal response, the process exits with code `3`. It does not switch to another account automatically.

Enable notifications with webhook environment variables:

```json
{
  "notifications": {
    "enabled": true,
    "webhooks": [
      {
        "name": "wecom",
        "kind": "wecom",
        "url_env": "AUTOTIANGONG_WECOM_WEBHOOK"
      }
    ]
  }
}
```

Webhook kinds supported by the standard library notifier are `generic`, `wecom`, `dingtalk`, and `telegram`. Email is also supported through `notifications.email` and SMTP environment variables.

## Windows host

The package uses only the Python standard library and can run on Windows with Python 3.10+:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
copy .env.example .env
copy config.example.json config.local.json
.\.venv\Scripts\python.exe -m autotiangong --config config.local.json --once --dry-run
```

For a foreground loop:

```powershell
.\.venv\Scripts\python.exe -m autotiangong --config config.local.json
```

To keep it running after sign-in, create a Windows Scheduled Task that starts in the project directory and runs:

```powershell
.\.venv\Scripts\python.exe -m autotiangong --config config.local.json
```

Or register that task from the project directory:

```powershell
.\scripts\install_windows_task.ps1 -RunAsCurrentUser
```

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

## Safety notes

- Use only accounts you are authorized to automate.
- Use the manual switch command only after administrator approval.
- Do not enable unattended account rotation around school or ISP quota limits.
- Do not commit `.env`, `config.local.json`, or logs.
- If a password was pasted into a chat, shell history, or log, rotate it.
- For a shared lab, prefer an official lab/service account from the network office and follow local network management rules.
