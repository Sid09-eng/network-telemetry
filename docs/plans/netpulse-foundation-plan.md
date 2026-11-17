# NetPulse delivery record

## Purpose

NetPulse is a reproducible network-operations demonstration: a Containerlab/FRRouting diamond
produces controlled traffic and faults; Prometheus and Grafana expose telemetry; forecasting and
anomaly services evaluate link utilisation; Alertmanager sends guarded remediation requests; and
Terraform describes the Linux deployment profile.

The project is intentionally synthetic. Its result documents describe completed runs rather than
claiming operator-network performance.

## Operating boundaries

- Run the topology from Linux. macOS is supported through the included Linux devcontainer or a
  remote Linux host.
- The devcontainer is privileged and uses the Docker Desktop socket; use it only for this checkout.
- Cloud identifiers, credentials, billing data, local state, raw captures, and audit logs remain
  outside Git.
- Live routing changes are disabled by default and require explicit runtime enablement.

## Delivery record

- [x] **Step 1 — Repository baseline.** Python packaging, local defaults, ignore rules, Make
  targets, and repository contracts are in place.
- [x] **Step 2 — Lab topology.** A deterministic FRR diamond provides OSPF convergence and two
  equal-cost paths between the traffic hosts.
- [x] **Step 3 — Telemetry collection.** Router-namespace exporters and Prometheus recording
  rules publish labelled link counters, throughput, and utilisation.
- [x] **Step 4 — Monitoring stack.** Compose provisions Prometheus, Grafana, Alertmanager,
  detection, remediation, and dashboard assets without taking ownership of the lab lifecycle.
- [x] **Step 5 — Controlled traffic and faults.** Seeded traffic schedules and allow-listed link
  scenarios emit timestamped ground truth.
- [x] **Step 6 — Run collection.** Prometheus range data is schema-validated and stored with
  immutable manifests and configuration hashes.
- [x] **Step 7 — Forecast evaluation.** Features are leakage-aware; rolling-origin and
  leave-one-link-out results are reported separately.
- [x] **Step 8 — Anomaly evaluation.** Residual scoring uses validation-selected thresholds and
  reports fault-matching metrics.
- [x] **Step 9 — Guarded remediation.** The Alertmanager webhook validates targets, serializes
  actions, enforces cooldowns, and defaults to dry-run.
- [x] **Step 10 — Recovery evidence.** Matched control and remediated experiments publish their
  source artifacts, restoration criterion, and MTTR calculation.
- [x] **Step 11 — GCP profile.** Terraform defines the restricted Compute Engine deployment and
  loopback-only service access.
- [x] **Step 12 — CI controls.** GitHub Actions runs tests, linting, image builds, Terraform
  validation, and Gitleaks; Dependabot tracks reviewed dependency updates.
- [x] **Step 13 — Reproducibility material.** The repository includes lifecycle commands,
  architecture, live demo evidence, result provenance, and operational limits.

## Verification model

| Area | Evidence |
| --- | --- |
| Topology | OSPF neighbours and ECMP route validation from live FRR routers |
| Telemetry | Prometheus scrape, recording-rule, and exporter contracts |
| Traffic and faults | Deterministic schedules with explicit applied/unapplied outcomes |
| Forecasting | Time-ordered and held-out-link evaluation |
| Remediation | Allow-list, dry-run, cooldown, rollback, and audit contracts |
| Recovery | Sustained-throughput restoration criterion over matched source runs |
| Deployment | Terraform formatting and validation without cloud credentials |

## Acceptance boundary

The public repository contains code, configuration, tests, sanitized evidence, and documentation.
Runtime captures, credentials, local Terraform state, and cloud billing data remain local. The
README is the operator entry point; the GCP deployment reference is intentionally limited to the
configuration and lifecycle decisions required to run this demonstration safely.
