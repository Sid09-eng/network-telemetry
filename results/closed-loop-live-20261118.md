# Closed-loop acceptance run — 18 November 2026

This record summarizes `closed-loop-20261118-live-008`, a successful controlled run against the
local Containerlab topology. It is evidence for one synthetic laboratory scenario; it is not a
production availability, capacity, or SLO claim.

## Outcome

The runner applied its bounded 1 Mb/s `tc netem` impairment to the selected synthetic path,
observed the detector and Prometheus alert, and verified that guarded remediation changed the
intended OSPF cost on `r1`. The alternate path carried the receiver traffic, meeting the declared
restoration criterion: three consecutive receiver samples at or above 90% of the pre-fault median.
The runner then removed the qdisc, observed the resolved-alert rollback, and the final topology
acceptance check returned the diamond to normal ECMP state.

| Signal | Observed value |
| --- | --- |
| Run ID | `closed-loop-20261118-live-008` |
| Fault to detector-active | 36.14 s |
| Fault to firing alert | 56.18 s |
| Measured restoration time | 56.43 s |
| Post-run route state | OSPF Full; two ECMP paths from `r1` to `h2` |

The restoration time is specific to this controlled impairment, traffic profile, thresholds, and
local runtime. It should not be interpreted as a general MTTR or a production service objective.

## Provenance

The complete evidence set remains local at
`runs/closed-loop-20261118-live-008/`. It is intentionally ignored by Git under `runs/*` because
it contains raw receiver output, route snapshots, alert payloads, and remediation audit records.
The run manifest records eight artifact SHA-256 values and five configuration SHA-256 values. Its
SHA-256 is:

```text
b59a821957b98a82510acca9c31d08048e3d9eedffaeb036eca904f03fd46162
```

This public summary retains only the run identifier, bounded outcome, timing, final topology
state, and manifest fingerprint. It deliberately omits raw captures, local addresses, container
logs, audit payloads, and local configuration.
