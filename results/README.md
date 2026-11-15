# Results

Only source-backed, reproducible result tables and plots belong here. Raw telemetry remains in
the ignored run directory that produced it; each published result must name its run ID and the
corresponding manifest hash.

`evaluate/mttr.py` uses the documented restoration criterion: end-to-end throughput must remain
at or above 90% of the pre-fault median for three consecutive samples. It emits no MTTR claim when
that sustained window is absent.
