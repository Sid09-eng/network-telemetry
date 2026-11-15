"""Append-only JSONL remediation audit writer."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def append_audit(path: Path, record: Mapping[str, Any]) -> None:
    """Durably append exactly one JSON object without rewriting previous records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(dict(record), sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "ab", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
