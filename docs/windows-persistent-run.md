# Windows Persistent Run Guide

Recommended production path on Windows: run AutoTiangong directly on the host with Windows Task Scheduler. This keeps the login request on the same host network stack as the browser and lets optional traffic guard code read Windows adapter counters.

Docker is included for development or controlled Linux deployments, but it is not the recommended Windows production path for this campus portal. Docker Desktop uses NAT/VM networking, so portal IP/MAC binding and host traffic counters may not match the Windows host.

## 1. Prepare The Project

Open PowerShell in the project directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
copy .env.example .env
copy config.example.json config.local.json
```

Edit `.env` and `config.local.json`. Keep real passwords only in `.env`.

## 2. Test Once

Use a dry run first:

```powershell
.\.venv\Scripts\python.exe -m autotiangong --config config.local.json --env-file .env --once --dry-run
```

After manually switching accounts, force one real login attempt so the online connectivity check does not skip the login:

```powershell
.\.venv\Scripts\python.exe -m autotiangong --config config.local.json --env-file .env --once --force-login --auto-switch --verbose
```

## 3. Install The Scheduled Task

Register a logon task and optionally start it immediately:

```powershell
.\scripts\install_windows_task.ps1 -RunAsCurrentUser -InstallDeps -StartNow
```

Useful options:

```powershell
.\scripts\install_windows_task.ps1 `
  -TaskName AutoTiangong `
  -ConfigPath config.local.json `
  -EnvFile .env `
  -IntervalSeconds 60 `
  -RunAsCurrentUser `
  -StartNow
```

Logs are written to:

```text
logs\autotiangong.log
```

The task runs:

```powershell
.\scripts\run_windows_daemon.ps1
```

That wrapper starts the Python daemon, appends stdout/stderr to the log file, and lets Task Scheduler restart it if the process exits unexpectedly.

## 4. Operate The Task

Check task status:

```powershell
Get-ScheduledTask -TaskName AutoTiangong
Get-ScheduledTaskInfo -TaskName AutoTiangong
```

Start, stop, or restart:

```powershell
Start-ScheduledTask -TaskName AutoTiangong
Stop-ScheduledTask -TaskName AutoTiangong
Stop-ScheduledTask -TaskName AutoTiangong; Start-ScheduledTask -TaskName AutoTiangong
```

View recent logs:

```powershell
Get-Content .\logs\autotiangong.log -Tail 80
```

Uninstall:

```powershell
.\scripts\uninstall_windows_task.ps1 -StopFirst
```

## 5. Docker Option

Build and run with Docker only after confirming container networking is acceptable for your network:

```powershell
docker compose -f docker-compose.example.yml up --build
```

For Docker state files, set paths in `config.local.json` to a mounted directory, for example:

```json
{
  "login": {
    "active_account_state_path": "/state/active-account.json",
    "auto_switch": {
      "unavailable_state_path": "/state/unavailable-accounts.json"
    }
  },
  "traffic_guard": {
    "enabled": false,
    "state_path": "/state/traffic.json"
  }
}
```

On Windows, prefer the Scheduled Task path unless a manual test proves Docker logs in the same client identity the campus portal expects.
