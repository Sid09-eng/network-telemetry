# Results

Published tables and plots are derived from reproducible runs. Raw telemetry stays with the
ignored run that produced it; published experiment results identify the run ID and manifest hash.

The synthetic forecast source run `runs/task7-variable-traffic-20261115/` is versioned with its
manifest and normalized telemetry. Its manifest hash is recorded in
[`forecast_metrics.md`](forecast_metrics.md), so the published forecast evaluation can be
reproduced without a live Prometheus server.

## Published live acceptance snapshot

[`live-demo-20261117.md`](live-demo-20261117.md) and its machine-readable companion
[`live-demo-20261117.json`](live-demo-20261117.json) record a bounded live-stack acceptance
check: topology, service readiness, remediation mode, scrape health, and selected live
throughput values. The snapshot names its ignored local source run and manifest SHA-256. It
intentionally excludes raw telemetry, container logs, private addresses, and local configuration.
It is not an MTTR claim or a production performance result.

`evaluate/mttr.py` uses the documented restoration criterion: end-to-end throughput must remain
at or above 90% of the pre-fault median for three consecutive samples. It emits no MTTR claim when
that sustained window is absent.

## Published closed-loop acceptance summary

[`closed-loop-live-20261118.md`](closed-loop-live-20261118.md) summarizes a successful local
closed-loop acceptance run: bounded impairment, detector and alert observation, guarded OSPF
remediation, sustained traffic restoration, and cleanup. The source run remains ignored locally;
the summary includes its run ID and manifest fingerprint but no raw telemetry, audit payloads, or
local configuration. Its measured restoration time applies only to that synthetic scenario.
