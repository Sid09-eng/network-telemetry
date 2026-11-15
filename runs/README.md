# Run artifacts

Each `runs/<run-id>/` directory is write-once and ignored by Git. A completed run contains:

- `raw/prometheus-range.json`: the unmodified Prometheus API response;
- `telemetry.jsonl`: the normalized, schema-validated samples;
- `faults/*.jsonl`: copied fault ground truth when supplied;
- `manifest.json`: query bounds, artifact paths, sample count, UTC creation time, and hashes of
  every configuration file used for collection.

Create a run from this Docker-outside-Docker devcontainer with the Prometheus container default:

```bash
python forecast/collect.py --run-id demo-001 --start 1794727800 --end 1794728100 --step 5
```

Use a new run ID for every collection. Existing IDs deliberately fail rather than being replaced.
