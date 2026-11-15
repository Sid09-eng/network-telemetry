# Anomaly metrics

Anomaly metrics will be published only after a completed run includes an applied, source-backed
fault interval and detector output. Evaluation matches at most one active detection to each
same-link fault from fault start through the configured post-fault matching window. Duplicate or
unmatched detections count as false positives; unmatched faults reduce recall. Thresholds are
selected from validation residuals only.
