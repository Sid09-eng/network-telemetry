# NetPulse

Simulated network telemetry, leakage-aware link-utilisation forecasting, anomaly detection, and guarded auto-remediation.

> Status: working demonstration environment with local evidence, GCP deployment validation,
> protected CI, and a captured live-stack demo. Cloud identifiers, local state, and credentials
> are intentionally excluded. Live remediation remains opt-in.

## Scope

NetPulse uses Containerlab and FRRouting to create a small synthetic network. It generates controlled traffic and link-failure events, observes router-interface telemetry with Prometheus and Grafana, predicts next-interval link utilisation, and routes alerts through Alertmanager to a protected remediation service.

The topology and traffic are synthetic. Forecast, anomaly, and recovery results are tied to their
recorded runs; they are not claims about a production network.

## Prerequisites

- Python 3.11 or 3.12 for project dependencies
- Linux host or Linux VM for Containerlab execution
- Docker with Compose v2
- Terraform 1.9+ and a GCP project with an approved budget for optional deployment

## Foundation setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
if [[ ! -f .env ]]; then
  cp .env.example .env
fi
make check
```

`NETPULSE_DRY_RUN=true` is default. Do not put GCP credentials, Terraform variables, Grafana state, fault captures, or remediation audit logs in Git.

## Linux quick start

Run this on a prepared **Linux** host, Linux VM, or the repository's Linux devcontainer. It needs
Python 3.11 or 3.12, Docker with Compose v2, Containerlab, `make`, and `curl`; the command checks
each prerequisite before making changes. It creates a local virtual environment, copies `.env`
only when it does not already exist, then validates the code, deploys the synthetic topology,
checks OSPF/ECMP, and starts monitoring.

```bash
git clone https://github.com/Sid09-eng/network-telemetry.git
cd network-telemetry
make quickstart
```

Expected final output includes `Topology healthy: all OSPF adjacencies Full; r1 has two ECMP paths
to h2.` and `NetPulse is ready`. The command waits for Prometheus readiness for up to 60 seconds
after Compose starts. Open Grafana at `http://127.0.0.1:3000`; its local credentials come from the
ignored `.env` file. On macOS, run these commands from the Linux devcontainer rather than the
macOS host terminal.

For a transparent equivalent (useful when diagnosing a prerequisite), the lifecycle command runs:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
if [[ ! -f .env ]]; then
  cp .env.example .env
fi
make check
make topology-up
make topology-check
make monitoring-up
wait_for_http() {
  local url="$1"
  local deadline=$((SECONDS + 60))
  local remaining
  while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    if (( remaining <= 0 )); then
      break
    fi
    curl --fail --silent --connect-timeout 2 --max-time "$remaining" "$url" && return 0
    if (( SECONDS < deadline )); then
      sleep 1
    fi
  done
  echo "Timed out waiting for ${url} after 60 seconds." >&2
  return 1
}
wait_for_http http://127.0.0.1:9090/-/ready
```

## Teardown

Stop the local monitoring containers and remove only the local Containerlab lab:

```bash
make teardown
```

`make teardown` expands to `make monitoring-down` followed by `make topology-down`; it does not
delete the repository, virtual environment, or GCP resources. If you deliberately provisioned the
optional GCP VM and no longer need it, review the Terraform plan and then run this separate,
destructive cloud cleanup command from the repository root:

```bash
terraform -chdir=infra/terraform destroy
```

That command destroys the Terraform-managed GCP VM, VPC, subnet, and firewall resources. It does
not affect local Docker or Containerlab resources.

## Continuous integration and secret scanning

GitHub Actions runs on pushes and pull requests to `main`. It installs Python development
dependencies, lints and tests the project, validates Compose syntax, builds service and
traffic-host images, and runs Terraform formatting/validation with no cloud credentials or
`terraform apply`. A separate Gitleaks job scans the full reachable Git history. Dependabot
opens weekly update pull requests for GitHub Actions and Python dependencies. Container-image
pins are changed only through an explicit, tested compatibility update.

Containerlab is deliberately excluded from hosted CI: its smoke test needs a stable privileged
Linux runner. Run the topology acceptance checks from the Linux devcontainer or the GCP host.

## Telemetry contract

Each FRR router has a fixed management address. A small exporter runs in each router namespace,
reads selected data-plane counters from `/sys/class/net`, and exposes port `9100`; it does not
execute router commands.

Prometheus scrapes raw byte, packet, error, and drop counters. [Recording rules](monitoring/recording_rules.yml) derive one-minute bits-per-second and utilisation ratios; raw counters stay raw. Default link capacity is 100 Mbps and is explicit in `NETPULSE_LINK_CAPACITY_BPS`.

## Available commands

```bash
make help
make test
make lint
make check
make topology-up
make topology-check
make topology-down
make monitoring-up
make monitoring-live-up
make monitoring-down
make closed-loop-trial RUN_ID=closed-loop-001
make terraform-fmt
make terraform-validate
```

## macOS Containerlab development

This repository includes a Docker-outside-Docker Linux devcontainer at [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json). In VS Code, install **Dev Containers**, open this folder, then run **Dev Containers: Reopen in Container**. The first launch pulls `ghcr.io/srl-labs/containerlab/devcontainer-dood-slim:0.83.0`.

Run topology commands from VS Code's devcontainer terminal, not macOS Terminal:

```bash
containerlab version
make topology-up
make topology-check
make topology-down
```

`topology-up` creates two equal-cost OSPF paths between `h1` and `h2`; `topology-check` requires each router to have two Full neighbours and `r1` to have two next hops to `10.0.4.0/24`.

## Monitoring stack

After topology health passes, `make monitoring-up` starts Prometheus, Grafana, Alertmanager,
the detector, the continuous forecaster, the remediation API, and the router exporters. The
forecaster polls the utilisation recording rule every five seconds, retains bounded in-memory
history, uses a persistence forecast, and publishes residual scores to the detector. Containerlab remains under the
topology lifecycle; `make monitoring-down` only removes the monitoring services. Grafana is
provisioned from the repository and bound to `http://127.0.0.1:3000`. The Link Overview dashboard
shows transmit throughput and utilisation alongside interface errors, drops, anomaly residuals,
and remediation action counters.

The devcontainer is privileged and has Docker socket access so it can manage labs and containers.
Use it only with this trusted checkout. Native network-namespace mounts are intentionally omitted
when Docker Desktop does not provide them.

Terraform defines one labelled Compute Engine VM, a dedicated network, and SSH access scoped to
`admin_cidr`. The VM has no attached service account; Grafana stays loopback-only and is reached
through an SSH tunnel. See the concise [GCP deployment reference](docs/gcp-deployment.md) and the
[delivery record](docs/plans/netpulse-foundation-plan.md).

## Traffic and faults

The traffic generator produces a deterministic 24-bucket compressed-day UDP plan: a smooth daily
load shape with bounded seeded noise and one or more reproducible bursts. The fault runner applies
only allow-listed diamond-link scenarios; both default to dry-run.

```bash
# Print a repeatable traffic plan; add --apply only to send UDP traffic from h1 to h2.
python traffic/generate.py --seed 17 --duration-seconds 120 \
  --target-rate-mbps 25 --scenario-id diamond-failover

# Record planned outage/recovery events without changing links.
python traffic/faults.py --scenario traffic/scenarios/diamond-failover.yaml \
  --log-path runs/diamond-failover-faults.jsonl
```

Use `--apply` on either command only for a controlled experiment. Fault application changes both
endpoints of a fixed inter-router link and writes an `applied` or `unapplied` JSONL record; it
never claims a failed command was injected. If endpoint compensation also fails, the record is
explicitly marked `partial-failure` with its rollback outcome.

## Forecast evaluation

Train only from a completed immutable run. The evaluator builds features using observations
through time *t*, predicts the next interval, and reports rolling-origin future-time metrics
separately from leave-one-link-out transfer metrics.

```bash
python -m forecast.train --run-dir runs/task7-variable-traffic-20261115
```

The plain command is evaluation-only: it writes the forecast report but does not change detector
state. To publish the optional detector handoff to a locally running monitoring stack:

```bash
python -m forecast.train --run-dir runs/task7-variable-traffic-20261115 \
  --detector-url http://127.0.0.1:8001
```

That command selects its threshold from earlier rolling-origin validation residuals, then scores
and publishes only the final chronological fold. It therefore does not use the targets being
scored to choose the threshold. Detector publishing requires at least two rolling-origin folds;
add `--detector-dry-run` to calculate the payloads without sending HTTP requests.

The committed report is source-backed by the versioned synthetic
[`task7-variable-traffic-20261115`](runs/task7-variable-traffic-20261115/) run and its manifest
hash. It remains a short synthetic experiment—not an operator-network performance claim.

## Guarded remediation

Alertmanager sends `NetPulseLinkAnomaly` alerts to the local FastAPI remediation webhook. The
service accepts only the fixed OSPF link allow-list (`r1-r2`, `r1-r3`, `r2-r4`, and `r3-r4`),
serializes decisions, applies monotonic per-interface and incident-wide cooldowns, and appends
audit JSONL records. Its Prometheus endpoint exports remediation status counters and last-action
latency. An alert resolution rolls back only a cost that the service previously applied.

Dry-run is the default. It records the exact allow-listed `docker exec ... vtysh` command but
never invokes Docker or changes a router. Test the webhook locally with:

```bash
curl --fail -X POST http://127.0.0.1:8000/alerts \
  -H 'Content-Type: application/json' \
  --data '{"version":"4","status":"firing","alerts":[{"status":"firing","labels":{"alertname":"NetPulseLinkAnomaly","link":"r1-r2"}}]}'
curl http://127.0.0.1:8000/metrics
```

Live OSPF cost changes require both `NETPULSE_DRY_RUN=false` and
`NETPULSE_ENABLE_LIVE_ACTIONS=true` in ignored `.env`; either setting alone is insufficient.
They additionally require the explicit socket-mount override, `make monitoring-live-up`. The
normal `make monitoring-up` dry-run stack does not mount the Docker socket. Do not enable live
mode until you have approved a controlled reroute test and a rollback/teardown plan.

## Controlled closed-loop trial

The closed-loop trial is separate from normal monitoring. It raises the `r1-r3` OSPF cost to 20
to force a 25 Mb/s UDP flow onto `r1-r2`, then applies a bounded `tc netem rate 1mbit` impairment to
`r1/eth1`. OSPF remains up while transmit utilisation drops. The forecaster publishes a negative
residual, Prometheus and Alertmanager route the alert, and remediation raises the `r1/eth1` OSPF
cost so traffic uses `r1-r3`. When the alert resolves, the service removes only the cost it
applied.

This is the only workflow that changes temporary routing and qdisc state. It needs the explicit
live remediation profile and a new run ID; cleanup removes the qdisc and both temporary route
costs even after a failed check. The runner rejects reused run IDs, an unsafe detector threshold,
stale audit records, incomplete cleanup, and missing detector, alert, applied-action, rollback,
alternate-route, or receiver-throughput evidence.
Restoration uses the repository's declared criterion: three consecutive receiver samples at or
above 90% of the pre-fault throughput median.

```bash
# In ignored .env, set both flags before the explicit live profile.
# NETPULSE_DRY_RUN=false
# NETPULSE_ENABLE_LIVE_ACTIONS=true
# NETPULSE_ANOMALY_THRESHOLD=0.01
make monitoring-live-up
make closed-loop-trial RUN_ID=closed-loop-20261118-001
```

The normal `0.1` threshold is intentionally too high for this 25 Mb/s-to-1 Mb/s rate trial.
The runner requires `0.01` or lower before it applies the impairment. Its 30-second baseline
ends before the forecaster's observed warm-up reversal; if remediation nevertheless acts before
the fault, the audit gate rejects the run without changing the qdisc. `make monitoring-live-up`
recreates the detector with the ignored `.env` profile.

Successful output is immutable under `runs/<RUN_ID>/`: receiver output, detector metrics,
Prometheus alerts, remediation audit snapshots, route output, event timestamps, and hashes of
the configuration used. Review and sanitize trial artifacts before committing them.

## Architecture

![NetPulse architecture](docs/architecture.svg)

The [architecture SVG](docs/architecture.svg) is self-contained and describes the synthetic
diamond topology, telemetry path, detection path, and guarded remediation boundary.

## Observed demo flow

The checked-in [demo GIF](docs/demo.gif) was captured from a verified live Linux run on 16
November 2026. It displays command output taken from the running services—not invented sample
values—and follows this flow:

1. `make topology-check` verifies four OSPF routers have Full adjacencies and `r1` has two ECMP
   paths to `h2`.
2. Prometheus `/-/ready` confirms the scrape server is ready; its API reports the active NetPulse
   targets.
3. Grafana's live `/api/health` response confirms the provisioned dashboard service and database
   are healthy. The dashboard itself is opened locally at `http://127.0.0.1:3000`.
4. A Prometheus query displays recorded transmit-throughput/utilisation data exported from router
   namespaces. The capture reads remediation's `/healthz` endpoint and displays its reported mode;
   it does not inject a fault, submit a remediation request, or change an OSPF cost.

## Evidence and provenance

| Evidence | Source and interpretation |
| --- | --- |
| Topology | `scripts/check_topology.py` checks live FRR OSPF and ECMP state. |
| Monitoring | Local Prometheus, Grafana, and remediation health endpoints provide the stack checks. |
| Live snapshot | [17 November 2026 summary](results/live-demo-20261117.md) and [JSON](results/live-demo-20261117.json) capture one controlled run, including the dry-run boundary. |
| Experiments | Immutable run manifests and [MTTR results](results/mttr_metrics.md) hold the reproducible synthetic experiment record. |
| Verification | **95 automated tests** run through `make test`; Ruff, Compose, Terraform, and Gitleaks run in [GitHub Actions](.github/workflows/ci.yml). |
| Deployment | [GCP deployment reference](docs/gcp-deployment.md) covers the loopback-only VM profile without committing cloud identifiers. |
| Demo | [docs/demo.gif](docs/demo.gif) is captured from a running local stack. |

## Limitations

- NetPulse models a small, synthetic FRR diamond; results do not demonstrate performance on an
  operator network or under Internet-scale traffic.
- Containerlab needs privileged Linux networking. Hosted CI intentionally does not run the live
  topology smoke test; it is run from a Linux devcontainer or the GCP host.
- The recorded experiments are finite and scenario-specific. Forecast quality, anomaly thresholds,
  and MTTR do not generalise without new representative data and controlled validation.
- The GIF verifies live service health and metrics endpoints. It is an evidence snapshot, not a
  substitute for the immutable experiment artifacts or an ongoing monitoring record.

## Security boundary

- Remediation is dry-run by default. A live OSPF change requires both explicit environment flags
  and the separate `make monitoring-live-up` socket-mount override.
- Router/link actions are allow-listed, serialized, cooldown-protected, and audit logged. Exporters
  read interface counters only; they do not execute router commands.
- Grafana, Prometheus, Alertmanager, detector, and remediation ports bind to loopback by default.
  The GCP design permits SSH only from the supplied administrator CIDR and attaches no VM service
  account.
- `.env`, Terraform state/variables, audit logs, captures, and cloud credentials are ignored. CI
  scans reachable history with Gitleaks; protected `main` requires its CI checks before merge.
