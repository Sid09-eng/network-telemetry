"""Task 3 router-interface exporter tests."""

import unittest
from pathlib import Path

from monitoring.exporter.app import collect_interface_metrics, render_metrics

COUNTERS = {
    "rx_bytes": 101,
    "tx_bytes": 202,
    "rx_packets": 3,
    "tx_packets": 4,
    "rx_errors": 0,
    "tx_errors": 1,
    "rx_dropped": 2,
    "tx_dropped": 0,
}


class InterfaceExporterTests(unittest.TestCase):
    def test_renders_labeled_router_counters_and_capacity(self) -> None:
        def reader(path: Path) -> int:
            return COUNTERS[path.name]

        samples, unreadable = collect_interface_metrics(
            router="r1",
            interface_links={"eth1": "r1-r2"},
            capacity_bps=100_000_000,
            reader=reader,
        )

        rendered = render_metrics(samples, unreadable)

        self.assertEqual(unreadable, [])
        self.assertIn(
            'netpulse_interface_receive_bytes_total{router="r1",interface="eth1",link="r1-r2"} 101',
            rendered,
        )
        self.assertIn(
            'netpulse_interface_capacity_bits_per_second{router="r1",interface="eth1",'
            'link="r1-r2"} 100000000',
            rendered,
        )

    def test_marks_interface_unreadable_when_counter_file_disappears(self) -> None:
        def reader(path: Path) -> int:
            if "eth2" in str(path):
                raise FileNotFoundError(path)
            return COUNTERS[path.name]

        samples, unreadable = collect_interface_metrics(
            router="r1",
            interface_links={"eth1": "r1-r2", "eth2": "r1-r3"},
            capacity_bps=100_000_000,
            reader=reader,
        )

        rendered = render_metrics(samples, unreadable)

        self.assertEqual(len(samples), 9)
        self.assertEqual(unreadable, [("r1", "eth2", "r1-r3")])
        self.assertIn(
            'netpulse_interface_readable{router="r1",interface="eth2",link="r1-r3"} 0',
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
