import os
import subprocess
import tempfile
import textwrap
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


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
