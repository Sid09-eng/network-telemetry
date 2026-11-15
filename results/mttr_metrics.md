# MTTR metrics

No comparative MTTR result is published yet. NetPulse defines restoration before measurement as
end-to-end throughput at least 90% of the pre-fault median for three consecutive samples.

Each future table must name its immutable source run and manifest SHA-256, and report fault start,
alert time, action start/end, restoration time, and MTTR. A control and remediated run must apply
the same impairment and use the same traffic schedule before they can be compared.

## 15 November 2026 synthetic netem comparison

Both 25-second UDP trials used the same 10 Mb/s flow and a 10-second, 100% loss impairment on
`r1/eth1`. Restoration is the first of three receiver-throughput samples at or above 90% of the
pre-fault median. This is a single short simulated experiment, not an operator-network claim.

| Mode | Source run | Manifest SHA-256 | Fault start | Action end | Restoration | MTTR |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Control | `task10-control-short-20261115` | `d7c0f26326e6e3a51c790b654a645e9353f4962064c61c77a4be5a6cb59fb73b` | 1794745774.872 | impairment removal 1794745784.980 | 1794745786.006 | 11.134 s |
| Remediated | `task10-remediated-short-20261115` | `0e795af1ee6eb358ffa98ab1fe9a692763f263474f21c2a2342ecd8c4936555e` | 1794745829.620 | 1794745834.774 | 1794745836.001 | 6.381 s |
