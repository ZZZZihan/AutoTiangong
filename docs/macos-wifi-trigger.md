# macOS Wi-Fi Trigger

Use the macOS LaunchAgent installer to run AutoTiangong when the current Wi-Fi
SSID becomes `360WiFi-E07A5C` or `TGU`.

```bash
./scripts/install_macos_wifi_launch_agent.sh --install-deps --start-now
```

The LaunchAgent checks the active Wi-Fi SSID every 10 seconds. While you remain
on either target network, the runner starts one lightweight AutoTiangong check
each interval. Repeated successful "already online" checks are summarized every
`--success-log-interval` seconds instead of writing three lines every poll; any
forced login, login attempt, account switch, unavailable marker, traffic guard
event, or failure is still logged immediately. If Dr.COM drops the current
account after a quota/session limit, that next check verifies the Dr.COM portal
`uid`/session state before deciding to skip login. If no active portal session
is reported, `--auto-switch` can immediately try the next configured account.
Consecutive failed checks are capped by `--max-retries` for the same connection,
then probed again after the retry cooldown.

The triggered command is:

```bash
.venv/bin/python -m autotiangong --config config.local.json --env-file .env --once --auto-switch --verbose
```

To force a login attempt on a new target-SSID connection even if the connectivity
check already appears online, install with:

```bash
./scripts/install_macos_wifi_launch_agent.sh --install-deps --start-now --force-login
```

After that first successful check, later checks on the same Wi-Fi connection use
the normal connectivity test so they do not keep submitting login requests while
the network is already online.

To customize the target networks, repeat `--ssid` once for each SSID:

```bash
./scripts/install_macos_wifi_launch_agent.sh \
  --ssid 360WiFi-E07A5C \
  --ssid TGU \
  --start-now \
  --force-login
```

Some recent macOS versions redact Wi-Fi SSIDs from command-line tools unless the
calling app has location permission. If logs show `Current Wi-Fi identity is
'router:...'` or the SSID is never detected, install with the current router
fingerprint as a fallback:

```bash
./scripts/install_macos_wifi_launch_agent.sh \
  --start-now \
  --force-login \
  --ssid 360WiFi-E07A5C \
  --ssid TGU \
  --router-ip 192.168.0.1 \
  --router-mac <router-mac>
```

Useful files:

- LaunchAgent plist: `~/Library/LaunchAgents/com.autotiangong.wifi-trigger.plist`
- Trigger log: `logs/macos-wifi-trigger.log`
- LaunchAgent stdout/stderr: `logs/macos-wifi-launchd.out.log` and
  `logs/macos-wifi-launchd.err.log`
- Trigger state: `.autotiangong-macos-wifi-trigger/`
- Account event log: `.autotiangong-account-events.jsonl`

Useful tuning options:

```bash
./scripts/install_macos_wifi_launch_agent.sh \
  --interval-seconds 10 \
  --max-retries 6 \
  --retry-cooldown 300 \
  --success-log-interval 300
```

To count actual account switches for the local day:

```bash
python -m autotiangong.switch_account --config config.local.json --history --today --history-limit 0
```

Uninstall:

```bash
./scripts/uninstall_macos_wifi_launch_agent.sh
```
