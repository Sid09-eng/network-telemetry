# Anomaly metrics

## Controlled closed-loop acceptance signal — 18 November 2026

Source run: `closed-loop-20261118-live-008`.
Source manifest SHA-256:
`b59a821957b98a82510acca9c31d08048e3d9eedffaeb036eca904f03fd46162`.

The source run contains one applied `r1-r2` rate impairment and one same-link negative-residual
detector activation. Its activation occurred 36.14 s after the fault began, so the observed
single-fault recall is **1.000 (1/1)**. The alert, live OSPF action, sustained restoration, and
rollback are recorded separately in
[the closed-loop acceptance summary](closed-loop-live-20261118.md).

| Metric | Observed value |
| --- | ---: |
| Applied source-backed faults | 1 |
| Matched same-link detector activations | 1 |
| Detection delay | 36.14 s |
| Single-fault recall | 1.000 (1/1) |
| False-positive count / precision | Not reported |

Precision is not reported: the sanitized public summary retains the matched detector snapshot,
not a complete scored observation window. Treating one retained activation as proof of zero false
positives would overstate the evidence. A multi-fault run with the full detector time series is
required before publishing aggregate precision, recall, or mean detection delay.

Evaluation matches at most one active detection to each same-link fault from fault start through
the configured post-fault matching window. Duplicate or unmatched detections count as false
positives; unmatched faults reduce recall. Thresholds are selected from validation residuals only.
