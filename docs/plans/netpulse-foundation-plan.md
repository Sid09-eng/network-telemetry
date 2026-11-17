# NetPulse Foundation Implementation Plan

## Goal

Create a reproducible, simulated network-operations project called **NetPulse**: a Containerlab/FRRouting topology generates real traffic and controlled link faults; Prometheus and Grafana display telemetry; a Python service forecasts link utilisation and detects anomalies; Alertmanager invokes a guarded remediation webhook; Terraform deploys the runnable stack to a GCP Linux host; GitHub Actions verifies the repository.

Delivery window is 15–20 November 2026. Local Linux validation comes first because Containerlab requires Linux; GCP deployment remains a required acceptance stage, not an optional feature. Deployment needs user-provided GCP project/billing scope and credentials, which must never enter source control. The project remains honest: synthetic traffic and faults, no claim of operator-network validation.

## New Linux devcontainer session handoff

### Current verified state

- Tasks 1–3 are complete in source and have **7/7 passing unit tests**.
- The macOS workspace uses the Docker-outside-Docker devcontainer in `.devcontainer/devcontainer.json`.
- Containerlab devcontainer image: `ghcr.io/srl-labs/containerlab/devcontainer-dood-slim:0.83.0`.
- The devcontainer runs as `root`, is privileged, and mounts Docker Desktop's socket at `${localEnv:HOME}/.docker/run/docker.sock`; this mount is required. Without it, Docker inside the container fails with `permission denied` on `/var/run/docker.sock`.
- A manual devcontainer-equivalent check passed on 15 November 2026: Docker server `29.9.3`; Containerlab `0.83.0`.
- No real Containerlab topology deployment has been claimed yet. FRR OSPF, Prometheus scrape, Grafana, traffic, faults, forecasting, remediation, Terraform, and CI still require live acceptance evidence.

### Start in VS Code

1. Open the repository in VS Code and run **Dev Containers: Rebuild and Reopen in Container**.
2. Start a new Codex session inside the reopened VS Code window. The repository is bind-mounted, so it contains all existing work; this new Codex session gets Linux/Docker access.
3. Before any new implementation, run:

   ```bash
   pwd
   containerlab version
   docker version
   make test
   ```

   Expected: Containerlab `0.83.0`, Docker server available, and `7/7` tests passing.

4. Run first live acceptance gate:

   ```bash
   make topology-up
   make topology-check
   ```

   Do not call Task 2 runtime-verified unless `topology-check` reports four routers with required Full OSPF neighbours and two `r1` next hops to `10.0.4.0/24`.

5. If either command fails, preserve its output, then run `docker ps -a` and `make topology-down`. Diagnose root cause before changing topology or devcontainer configuration.

### Exact starter prompt for new Codex session

```text
Continue NetPulse in this Linux devcontainer. Read README.md and docs/plans/netpulse-foundation-plan.md first. Do not redo Tasks 1–3. Verify `containerlab version`, `docker version`, and `make test`; then run `make topology-up` and `make topology-check`. Investigate any failure before editing. If live topology passes, implement Task 4 with TDD and preserve Task 1–3 behaviour.
```

### Reuse versus new work

- Reuse: `.devcontainer/devcontainer.json`, `topology/netpulse.clab.yml`, all four FRR startup configurations, `scripts/check_topology.py`, router-interface exporter, Prometheus configuration/rules, unit tests, Makefile, and README safety boundaries.
- New next: Task 4 Compose stack, Grafana provisioning/dashboard, Alertmanager wiring; only begin after the live topology gate passes.

## Audit and design decisions

- The workspace currently contains only `network-telemetry-plan.md`; no Git repository, source code, deployment configuration, or existing tests exist to reuse.
- Reuse the existing FYP approach conceptually: persistence comparison, strict chronological/rolling-origin evaluation, separate leave-one-link-out transfer evaluation, and metrics reported only from a completed run.
- Use Containerlab and FRRouting in a Linux environment. macOS can edit the project but should run the topology through a Linux VM or remote Linux host.
- Use a small custom Prometheus exporter that runs in each router container/namespace and reads `/sys/class/net/*/statistics/{rx,tx}_{bytes,packets,errors,dropped}`. This is more direct and reliable for per-router-link counters than assuming `node_exporter` exposes every Containerlab interface. Node exporter may later supplement host/container health metrics.
- Start with a four-router diamond (`r1-r2-r4` and `r1-r3-r4`) plus two Linux traffic hosts. OSPF provides an alternate path so changing an interface cost is observable.
- Alertmanager is the control-plane trigger. The detector exposes an anomaly gauge through a Prometheus scrape endpoint; an alert rule evaluates it and posts to the FastAPI service. The detector does **not** directly execute router actions.
- Remediation starts in dry-run mode, has an allow-list of router/interface targets, uses a monotonic cooldown, logs an immutable JSONL audit record, and only enables live router changes with an explicit configuration flag.
- Record MTTR for comparable fault scenarios with remediation disabled and enabled. Define restoration before collecting results (for example, sustained throughput at least 90% of pre-fault median for three scrape intervals).
- Five-day sequencing: Day 1 foundation/topology; Day 2 telemetry/dashboard/traffic; Day 3 collection/forecasting/faults; Day 4 alert/remediation/MTTR; Day 5 Terraform deployment, CI, clean-clone test, README and demo evidence. Keep GCP/Terraform and CI; cut optional rollback polish or advanced model selection before cutting cloud delivery.

## Implementation checklist

- [x] Task 1 — initialise the Python/Git project, supported versions, `.gitignore`, `.env.example`, README skeleton, and Makefile commands. Keep secrets, GCP credentials, Grafana state, audit logs, raw captures, and local Terraform state out of version control. (files: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `Makefile`)

- [x] Task 2 — define the deterministic Containerlab diamond topology, FRRouting OSPF configurations, image/version pins, and a topology health check that verifies all expected adjacencies and the alternate route. (files: `topology/netpulse.clab.yml`, `topology/configs/*.conf`, `scripts/check_topology.py`)

- [x] Task 3 — add a router-interface metrics exporter and Prometheus scrape configuration. Export stable labels for router, interface, link, direction, and counter; derive per-second utilisation from rates in recording rules rather than from raw counters in application code. (files: `monitoring/exporter/app.py`, `monitoring/exporter/Dockerfile`, `monitoring/prometheus.yml`, `monitoring/recording_rules.yml`)

- [x] Task 4 — compose Prometheus, Grafana, Alertmanager, detector, remediation API, and only the supporting services that need Compose. Keep Containerlab deployment a separate Makefile target so Docker Compose does not obscure network lifecycle. Provision Grafana datasource/dashboard declaratively. (files: `docker-compose.yml`, `monitoring/grafana/provisioning/**`, `monitoring/grafana/dashboards/link-overview.json`, `monitoring/alertmanager.yml`)

- [x] Task 5 — implement repeatable traffic generation and fault scenarios. Traffic schedules must take a seed, compressed-day duration, target rate, and scenario ID; fault events must log planned/applied timestamps, target link, action, parameters, and outcome in JSONL. (files: `traffic/generate.py`, `traffic/faults.py`, `traffic/scenarios/*.yaml`)

- [x] Task 6 — implement data collection from Prometheus range queries, schema validation, and immutable run manifests. Retain raw telemetry, fault ground truth, and configuration hashes per run so model results can be reproduced. (files: `forecast/collect.py`, `forecast/schema.py`, `runs/README.md`, `results/README.md`)

- [x] Task 7 — implement feature building, baselines, models, and evaluation. All lag/rolling features at time *t* must use observations through *t* only; the target is utilisation at *t + horizon*. Evaluate persistence, seasonal-naive, Ridge, and HistGradientBoosting with rolling-origin folds; report a distinct leave-one-link-out evaluation rather than mixing it with future-time performance. (files: `forecast/features.py`, `forecast/models.py`, `forecast/evaluate.py`, `forecast/train.py`, `results/forecast_metrics.md`)

- [x] Task 8 — implement residual-based anomaly scoring and fault-ground-truth evaluation. Thresholds must be chosen using validation data only; calculate precision, recall, false-positive count, and detection delay with an explicit matching window. Expose anomaly score/state for Prometheus scraping. (files: `forecast/detect.py`, `detector/app.py`, `monitoring/alert_rules.yml`, `results/anomaly_metrics.md`)

- [x] Task 9 — implement the FastAPI Alertmanager webhook and safe OSPF-cost remediation adapter. Validate webhook payloads, reject unrecognised targets, default to dry run, lock concurrent actions, enforce cooldown, capture action/rollback output, and publish remediation latency/status metrics. Live OSPF changes remain explicitly disabled pending a controlled operator-approved reroute test. (files: `remediation/app.py`, `remediation/actions.py`, `remediation/policy.py`, `remediation/audit.py`, `remediation/Dockerfile`)

- [x] Task 10 — run comparative recovery scenarios and create committed, source-backed result tables/plots only after successful runs. Report fault start, alert time, action start/end, restoration time, and MTTR definition; do not prefill CV claims. (files: `evaluate/mttr.py`, `results/mttr_metrics.md`, `results/*.csv`, `results/*.png`)

- [x] Task 11 — add Terraform for a required GCP Compute Engine Linux host, scoped firewall rules, labels, startup script, variables, outputs, and a budget-alert design. The runnable stack was deployed and verified on an approved user-owned GCP project: Docker and pinned Containerlab bootstrapped, the OSPF/ECMP topology passed, and the monitoring stack was reached through a private SSH tunnel. Do not commit credentials, project identifiers, local state, or actual billing configuration; document `terraform destroy` and cost controls. (files: `infra/terraform/*.tf`, `infra/terraform/startup.sh`, `infra/terraform/terraform.tfvars.example`, `docs/gcp-deployment.md`)

- [x] Task 12 — add CI that installs Python dependencies, runs formatting/lint/unit tests, builds service images, validates Compose syntax, and runs `terraform fmt -check` plus `terraform validate` without cloud credentials. A separate Gitleaks job scans reachable Git history; Dependabot tracks GitHub Actions and Python dependencies. Container-image pins change only through an explicit compatibility-tested update. The first `main` workflow passed. Add Containerlab smoke testing only after it is stable in a privileged Linux runner. (files: `.github/workflows/ci.yml`, `.github/dependabot.yml`)

- [x] Task 13 — finish reproducibility documentation: a Linux `make quickstart` / `make teardown` lifecycle, observed demo flow, architecture diagram, limitations, security boundary, test count, results provenance, and a 30-second GIF generated from live topology, Prometheus, and Grafana health evidence. (files: `README.md`, `docs/architecture.svg`, `docs/demo.gif`, `scripts/capture_demo_gif.py`)

## Required tests

| Area | Core behaviour | Edge case |
|---|---|---|
| Topology checks | Expected OSPF neighbours/routes are present | Missing alternate path fails with a diagnostic |
| Metrics exporter | Converts available interface counters to valid Prometheus samples | Interface disappears or counter file is unreadable |
| Traffic/fault scheduler | Same seed/scenario yields the same scheduled events | A command failure is logged as unapplied, not claimed as injected |
| Feature builder | No feature at *t* reads a value after *t* | Gaps, first lag rows, and insufficient rolling history |
| Evaluation | Rolling folds keep training strictly before validation/test | A fold with too little training data is skipped/reported |
| Link-transfer evaluation | Held-out link is absent from train data | Only one link available produces a clear configuration error |
| Anomaly evaluator | Scores detections against fault intervals and reports delay | Multiple detections for one fault and faults with no detection |
| Remediation policy | Valid alert creates a dry-run audit entry | Unauthorised target, malformed webhook, cooldown active, duplicate alert |
| Router adapter | Live mode issues only an allow-listed OSPF cost change | Router command timeout triggers failed action/rollback record |
| MTTR evaluator | Applies the documented sustained-restoration criterion | No restoration before experiment timeout |
| IaC/CI | Terraform formatting/validation and CI config parse cleanly | Missing GCP variables never cause credential use in CI |

## Acceptance sequence

1. On Linux, deploy the topology and monitoring stack and show live interface throughput.
2. Run a seeded traffic/fault scenario and preserve the corresponding run manifest/ground truth.
3. Train/evaluate only on collected telemetry and publish measured baseline comparisons.
4. Demonstrate detector -> Prometheus rule -> Alertmanager -> dry-run webhook, then explicitly enable one controlled live reroute test.
5. Publish measured MTTR comparison, tests, CI evidence, and limitations.
6. Deploy and verify NetPulse on GCP after local acceptance and after the user supplies approved project/billing scope; destroy resources after demo unless the user requests they remain running.
