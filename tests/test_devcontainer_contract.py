"""Local Linux Containerlab devcontainer contract."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DevcontainerContractTests(unittest.TestCase):
    def test_dood_container_has_required_linux_runtime_access(self) -> None:
        path = ROOT / ".devcontainer" / "devcontainer.json"
        config = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            config["image"],
            "ghcr.io/srl-labs/containerlab/devcontainer-dood-slim:0.83.0",
        )
        self.assertEqual(
            config["runArgs"],
            ["--network=host", "--pid=host", "--privileged"],
        )
        self.assertEqual(
            config["workspaceFolder"],
            "${localWorkspaceFolder}",
        )
        self.assertEqual(
            config["workspaceMount"],
            "source=${localWorkspaceFolder},target=${localWorkspaceFolder},type=bind",
        )
        self.assertEqual(config["remoteUser"], "root")
        self.assertEqual(
            config["mounts"],
            [
                "type=bind,src=/var/lib/docker,dst=/var/lib/docker",
                "type=bind,src=/lib/modules,dst=/lib/modules",
                "type=bind,source=${localEnv:HOME}/.docker/run/docker.sock,target=/var/run/docker.sock",
            ],
        )


if __name__ == "__main__":
    unittest.main()
