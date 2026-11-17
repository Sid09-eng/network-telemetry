# Results

Only source-backed, reproducible result tables and plots belong here. Raw telemetry remains in
the ignored run directory that produced it; each published result must name its run ID and the
corresponding manifest hash.

## Published live acceptance snapshot

[`live-demo-20261117.md`](live-demo-20261117.md) and its machine-readable companion
[`live-demo-20261117.json`](live-demo-20261117.json) record a bounded live-stack acceptance
check: topology, service readiness, remediation mode, scrape health, and selected live
throughput values. They intentionally exclude raw telemetry, container logs, private addresses,
and local configuration. They are not an MTTR claim or a production performance result.

`evaluate/mttr.py` uses the documented restoration criterion: end-to-end throughput must remain
at or above 90% of the pre-fault median for three consecutive samples. It emits no MTTR claim when
that sustained window is absent.
