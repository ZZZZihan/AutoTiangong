import os
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


class MacosWifiTriggerTest(unittest.TestCase):
    def test_redacted_networksetup_ssid_uses_router_identity(self):
        repo = Path(__file__).resolve().parents[1]
        script = repo / "scripts" / "run_macos_wifi_trigger.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "project"
            fake_bin = Path(tmpdir) / "bin"
            project_dir.mkdir()
            fake_bin.mkdir()
            (project_dir / "config.local.json").write_text("{}", encoding="utf-8")
            (project_dir / ".env").write_text("", encoding="utf-8")
            python_log = project_dir / "python.args"

            _write_executable(
                fake_bin / "networksetup",
                """\
                #!/usr/bin/env bash
                if [[ "$1" == "-listallhardwareports" ]]; then
                    printf 'Hardware Port: Wi-Fi\\nDevice: en0\\n'
                elif [[ "$1" == "-getairportnetwork" ]]; then
                    printf 'Current Wi-Fi Network: <redacted>\\n'
                fi
                """,
            )
            _write_executable(
                fake_bin / "ipconfig",
                """\
                #!/usr/bin/env bash
                if [[ "$1" == "getoption" ]]; then
                    printf '192.168.0.1\\n'
                fi
                """,
            )
            _write_executable(fake_bin / "ping", "#!/usr/bin/env bash\nexit 0\n")
            _write_executable(
                fake_bin / "arp",
                """\
                #!/usr/bin/env bash
                printf '? (192.168.0.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]\\n'
                """,
            )
            _write_executable(
                fake_bin / "python",
                f"""\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" > {python_log}
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                [
                    str(script),
                    "--project-dir",
                    str(project_dir),
                    "--python-path",
                    str(fake_bin / "python"),
                    "--router-ip",
                    "192.168.0.1",
                    "--router-mac",
                    "aa:bb:cc:dd:ee:ff",
                    "--max-retries",
                    "1",
                ],
                text=True,
                capture_output=True,
                env=env,
                timeout=10,
            )

            log = (project_dir / "logs" / "macos-wifi-trigger.log").read_text(encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout + log)
            self.assertIn("Matched '360WiFi-E07A5C' as router:192.168.0.1:aa:bb:cc:dd:ee:ff", log)
            self.assertTrue(python_log.exists())

    def test_repeated_successful_checks_are_suppressed_until_interval(self):
        repo = Path(__file__).resolve().parents[1]
        script = repo / "scripts" / "run_macos_wifi_trigger.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "project"
            fake_bin = Path(tmpdir) / "bin"
            project_dir.mkdir()
            fake_bin.mkdir()
            (project_dir / "config.local.json").write_text("{}", encoding="utf-8")
            (project_dir / ".env").write_text("", encoding="utf-8")

            _write_executable(
                fake_bin / "networksetup",
                """\
                #!/usr/bin/env bash
                if [[ "$1" == "-listallhardwareports" ]]; then
                    printf 'Hardware Port: Wi-Fi\\nDevice: en0\\n'
                elif [[ "$1" == "-getairportnetwork" ]]; then
                    printf 'Current Wi-Fi Network: 360WiFi-E07A5C\\n'
                fi
                """,
            )
            _write_executable(fake_bin / "ipconfig", "#!/usr/bin/env bash\nexit 0\n")
            _write_executable(
                fake_bin / "python",
                """\
                #!/usr/bin/env bash
                printf '2026-05-05 09:25:40,307 INFO Network is online; Login not needed.\\n'
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            command = [
                str(script),
                "--project-dir",
                str(project_dir),
                "--python-path",
                str(fake_bin / "python"),
                "--success-log-interval",
                "300",
            ]

            first = subprocess.run(command, text=True, capture_output=True, env=env, timeout=10)
            second = subprocess.run(command, text=True, capture_output=True, env=env, timeout=10)

            log = (project_dir / "logs" / "macos-wifi-trigger.log").read_text(encoding="utf-8")
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout + log)
            self.assertEqual(second.returncode, 0, second.stderr + second.stdout + log)
            self.assertEqual(log.count("Matched '360WiFi-E07A5C'"), 1)
            self.assertEqual((project_dir / ".autotiangong-macos-wifi-trigger" / "suppressed_success_count").read_text(encoding="utf-8").strip(), "1")

    def test_session_alignment_output_bypasses_success_suppression(self):
        repo = Path(__file__).resolve().parents[1]
        script = repo / "scripts" / "run_macos_wifi_trigger.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "project"
            fake_bin = Path(tmpdir) / "bin"
            state_dir = project_dir / ".autotiangong-macos-wifi-trigger"
            project_dir.mkdir()
            fake_bin.mkdir()
            state_dir.mkdir()
            (project_dir / "config.local.json").write_text("{}", encoding="utf-8")
            (project_dir / ".env").write_text("", encoding="utf-8")
            (state_dir / "last_ssid").write_text("ssid:360WiFi-E07A5C\n", encoding="utf-8")
            (state_dir / "last_success_log_epoch").write_text(f"{int(time.time())}\n", encoding="utf-8")
            (state_dir / "suppressed_success_count").write_text("2\n", encoding="utf-8")

            _write_executable(
                fake_bin / "networksetup",
                """\
                #!/usr/bin/env bash
                if [[ "$1" == "-listallhardwareports" ]]; then
                    printf 'Hardware Port: Wi-Fi\\nDevice: en0\\n'
                elif [[ "$1" == "-getairportnetwork" ]]; then
                    printf 'Current Wi-Fi Network: 360WiFi-E07A5C\\n'
                fi
                """,
            )
            _write_executable(fake_bin / "ipconfig", "#!/usr/bin/env bash\nexit 0\n")
            _write_executable(
                fake_bin / "python",
                """\
                #!/usr/bin/env bash
                printf '2026-05-05 09:25:40,307 INFO Active account state aligned with Dr.COM session as account id lab-secondary.\\n'
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                [
                    str(script),
                    "--project-dir",
                    str(project_dir),
                    "--python-path",
                    str(fake_bin / "python"),
                    "--success-log-interval",
                    "300",
                ],
                text=True,
                capture_output=True,
                env=env,
                timeout=10,
            )

            log = (project_dir / "logs" / "macos-wifi-trigger.log").read_text(encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout + log)
            self.assertIn("Suppressed 2 repeated successful check(s)", log)
            self.assertIn("Active account state aligned with Dr.COM session as account id lab-secondary.", log)
            self.assertEqual((state_dir / "suppressed_success_count").read_text(encoding="utf-8").strip(), "0")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
