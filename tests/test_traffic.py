import json
import tempfile
import unittest
from pathlib import Path

from autotiangong.config import TrafficGuardConfig
from autotiangong.traffic import TrafficGuard, _parse_netstat_ibn


class FakeCounter:
    def __init__(self, total_bytes):
        self.total_bytes = total_bytes
        self.interfaces = []

    def read_total_bytes(self, interface=None):
        self.interfaces.append(interface)
        return self.total_bytes


class TrafficGuardTest(unittest.TestCase):
    def test_tracks_usage_without_storing_username(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "traffic.json"
            counter = FakeCounter(1_000)
            guard = TrafficGuard(
                TrafficGuardConfig(enabled=True, limit_bytes=100, state_path=str(state_path), interface="Ethernet"),
                counter=counter,
            )

            activated = guard.activate("alice@example")
            self.assertTrue(activated.ok)
            self.assertEqual(activated.used_bytes, 0)
            self.assertEqual(counter.interfaces, ["Ethernet"])

            counter.total_bytes = 1_050
            below_limit = guard.check()
            self.assertTrue(below_limit.ok)
            self.assertEqual(below_limit.used_bytes, 50)

            counter.total_bytes = 1_100
            at_limit = guard.check()
            self.assertFalse(at_limit.ok)
            self.assertEqual(at_limit.used_bytes, 100)

            raw_state = state_path.read_text(encoding="utf-8")
            self.assertNotIn("alice@example", raw_state)
            self.assertEqual(json.loads(raw_state)["account_label"], "al***le")

    def test_parses_darwin_netstat_without_double_counting_interfaces(self):
        output = """Name  Mtu   Network     Address            Ipkts Ierrs Ibytes    Opkts Oerrs Obytes Coll
en0   1500  <Link#4>    aa:bb:cc:dd:ee:ff 1     0     100       1     0     50     0
en0   1500  192.168.1   192.168.1.2        1     0     100       1     0     50     0
lo0   16384 <Link#1>                       1     0     10        1     0     15     0
"""

        self.assertEqual(_parse_netstat_ibn(output), 175)
        self.assertEqual(_parse_netstat_ibn(output, "en0"), 150)


if __name__ == "__main__":
    unittest.main()
