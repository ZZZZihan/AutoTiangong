# AutoTiangong

Authorized campus portal guard for a lab gateway or a personal machine.

AutoTiangong can register multiple authorized accounts and optionally fail over when the portal/login response indicates the current account is unavailable, authentication failed, or the session is abnormal. Switching is driven by explicit portal/status signals, and the optional local traffic guard can rotate accounts only when auto-switch is enabled; there is no implicit fixed 4.9 GiB threshold.

## What it does

- Detects captive portal status with an HTTP connectivity endpoint.
- Verifies Dr.COM portal session state before skipping login on an online network.
- Parses Dr.COM portal settings from the landing page when available.
- Sends a configurable Dr.COM login request with the administrator-selected authorized account.
- Can optionally try the next registered account after login failure or configured account-unavailable markers.
- Can mark unavailable accounts in local state, skip them for the current reset window, and restore them manually.
- Supports a local registry of multiple authorized lab accounts without storing passwords in config or state.
- Supports JSON or YAML config files.
- Provides a manual account switch command for administrators.
- Can stop automatically when local traffic for the current login session reaches a configured guardrail such as 4.9 GiB.
- Can treat configured portal response text such as quota, disabled-account, password-error, or session-error messages as account-unavailable signals.
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

YAML configs are also supported:

```bash
cp config.example.yaml config.local.yaml
```

Edit `.env` locally:

```bash
CAMPUS_NET_USERNAME=your_authorized_lab_or_personal_account
CAMPUS_NET_PASSWORD=your_password
CAMPUS_NET_USERNAME_2=another_authorized_lab_account
CAMPUS_NET_PASSWORD_2=another_password
```

If `login.accounts` is omitted, AutoTiangong can discover `_2`, `_3`, ... numbered env pairs after `load_env_file`, or you can define `AUTOTIANGONG_ACCOUNTS` as:

```bash
AUTOTIANGONG_ACCOUNTS=lab-primary:CAMPUS_NET_USERNAME:CAMPUS_NET_PASSWORD,lab-secondary:CAMPUS_NET_USERNAME_2:CAMPUS_NET_PASSWORD_2
```

Run a safe dry run:

```bash
python -m autotiangong --config config.local.json --once --dry-run
```

Run one real login attempt if the connectivity check fails:

```bash
python -m autotiangong --config config.local.json --once
```

Force a login attempt after manually switching the active account:

```bash
python -m autotiangong --config config.local.json --once --force-login
```

Run as a foreground loop:

```bash
python -m autotiangong --config config.local.json
```

On macOS, install a Wi-Fi trigger that runs a lightweight AutoTiangong check
while the current SSID is `360WiFi-E07A5C`:

```bash
./scripts/install_macos_wifi_launch_agent.sh --install-deps --start-now
```

See `docs/macos-wifi-trigger.md` for logs, retry behavior, and uninstall steps.

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
- `login.kernel_port`: optional Dr.COM kernel port used when the rendered portal login falls back to `/drcom/login`; `null` means reuse `portal_url` host/port.
- `login.fallback_to_kernel`: when true, tries the kernel login endpoint if the rendered ePortal response is inconclusive.
- `login.auto_switch.enabled`: when true, tries each registered account once after login failure or account-unavailable markers.
- `login.auto_switch.persist_success`: when true, records the account that succeeds after failover as the new active account.
- `login.auto_switch.strategy`: `round_robin` starts from the current active account; `random` shuffles the configured pool each run.
- `login.auto_switch.unavailable_state_path`: local state file for accounts temporarily marked unavailable.
- `login.auto_switch.unavailable_reset_days`: number of days before an unavailable marker auto-expires; `1` means next-day reset.
- `login.extra_fields`: non-secret Dr.COM parameters.
- `login.username_env` and `login.password_env`: environment variable names used for secrets.
- `login.account_unavailable_markers`: response text snippets that mark the current account unavailable and allow failover.
- `login.quota_limit_markers`: backward-compatible quota snippets; these are also treated as account-unavailable signals.
- `logout.enabled`: enables best-effort logout when the daemon stops for the optional local traffic guardrail.
- `notifications.enabled`: enables webhook/email admin notifications for traffic guard stops and account-unavailable events.
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
    "kernel_port": null,
    "fallback_to_kernel": true,
    "auto_switch": {
      "enabled": false,
      "persist_success": true,
      "strategy": "round_robin",
      "unavailable_state_path": ".autotiangong-unavailable-accounts.json",
      "unavailable_reset_days": 1
    },
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

When the optional local traffic guardrail is reached, the process exits with code `3` unless `login.auto_switch.enabled` is true. With auto-switch enabled, the current account is marked unavailable for the reset window and AutoTiangong immediately tries the next configured account. Portal quota/unavailable messages are handled through `login.account_unavailable_markers`/`login.quota_limit_markers`: the current account is marked unavailable and auto-switch can try the next account.

To enable automatic failover for account-unavailable and login-failure responses, set:

```json
{
  "login": {
    "auto_switch": {
      "enabled": true,
      "persist_success": true,
      "strategy": "round_robin",
      "unavailable_reset_days": 1
    },
    "account_unavailable_markers": [
      "账号不可用",
      "流量已用尽",
      "已达上限",
      "禁用",
      "password error",
      "authfail",
      "会话异常"
    ]
  }
}
```

The daemon starts with the current active account, skips accounts already marked unavailable, then tries each candidate once according to `strategy`. It skips accounts whose username/password environment variables are missing, writes account-unavailable markers to `login.auto_switch.unavailable_state_path`, and writes the first successful failover account to `login.active_account_state_path` only when `persist_success` is true.

Inspect or clear unavailable markers:

```bash
python -m autotiangong.switch_account --config config.local.json --unavailable
python -m autotiangong.switch_account --config config.local.json --restore lab-primary
python -m autotiangong.switch_account --config config.local.json --restore-all
```

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

For a Windows machine that should run AutoTiangong all the time, use Windows Task Scheduler. This is the recommended production path because the process runs on the same host network stack as the browser.

Full guide: [Windows Persistent Run Guide](docs/windows-persistent-run.md).

The package can run on Windows with Python 3.10+:

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

To keep it running after sign-in, register the included scheduled task:

```powershell
.\scripts\install_windows_task.ps1 -RunAsCurrentUser -InstallDeps -StartNow
```

Logs are written to `logs\autotiangong.log`.

To uninstall:

```powershell
.\scripts\uninstall_windows_task.ps1 -StopFirst
```

## Docker

Docker artifacts are included for development or controlled deployments:

```bash
docker compose -f docker-compose.example.yml up --build
```

For Windows campus-portal use, prefer the Scheduled Task path unless you have verified Docker Desktop networking logs in as the same client identity the portal expects. Docker NAT can change IP/MAC behavior, and containerized traffic counters do not represent the Windows host adapter counters.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

## Safety notes

- Use only accounts you are authorized to automate.
- Use the manual switch command or automatic failover only for accounts you are authorized to operate.
- Do not use unattended account switching to evade school, ISP, or organization policy.
- Do not commit `.env`, `config.local.json`, or logs.
- If a password was pasted into a chat, shell history, or log, rotate it.
- For a shared lab, prefer an official lab/service account from the network office and follow local network management rules.
