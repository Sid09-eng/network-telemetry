"""Task 2 topology-health tests."""

import unittest

from scripts.check_topology import assess_router, wait_for_topology

FULL_NEIGHBOURS = """\
Neighbor ID     Pri State           Dead Time Address         Interface
10.255.0.2        1 Full/DR           00:00:31 10.0.12.2      eth1
10.255.0.3        1 Full/Backup       00:00:34 10.0.13.2      eth2
"""

ECMP_ROUTE = """\
Routing entry for 10.0.4.0/24
  Known via \"ospf\", distance 110, metric 20
  * 10.0.12.2, from 10.255.0.2, via eth1
  * 10.0.13.2, from 10.255.0.3, via eth2
"""


class TopologyHealthTests(unittest.TestCase):
    def test_router_passes_when_ospf_neighbours_and_ecmp_route_are_ready(self) -> None:
        def runner(command: list[str]) -> str:
            return FULL_NEIGHBOURS if "neighbor" in command[-1] else ECMP_ROUTE

        self.assertEqual(assess_router("r1", runner), [])

    def test_router_reports_missing_ecmp_path(self) -> None:
        def runner(command: list[str]) -> str:
            return FULL_NEIGHBOURS if "neighbor" in command[-1] else ECMP_ROUTE.splitlines()[0]

        failures = assess_router("r1", runner)

        self.assertEqual(failures, ["r1: expected at least 2 next hops to 10.0.4.0/24; found 0"])

    def test_waits_for_transient_ospf_convergence(self) -> None:
        outcomes = [["r1: expected 2 Full OSPF neighbours; found 0"], []]
        sleeps: list[float] = []

        failures = wait_for_topology(
            lambda: outcomes.pop(0), attempts=3, retry_interval=5, sleeper=sleeps.append
        )

        self.assertEqual(failures, [])
        self.assertEqual(sleeps, [5])


if __name__ == "__main__":
    unittest.main()
