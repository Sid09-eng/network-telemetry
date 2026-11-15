# NetPulse

Simulated network telemetry, leakage-aware link-utilisation forecasting, anomaly detection, and guarded auto-remediation.

> Status: Tasks 1–10 are implemented with source-backed local evidence. Task 11 Terraform
> configuration is locally formatted and provider-validated; GCP deployment remains pending
> approved project, billing, and operator credentials. A live remediation test requires explicit
> operator enablement.

## Scope

NetPulse uses Containerlab and FRRouting to create a small synthetic network. It generates controlled traffic and link-failure events, observes router-interface telemetry with Prometheus and Grafana, predicts next-interval link utilisation, and routes alerts through Alertmanager to a protected remediation service.

Synthetic topology and traffic are demonstration data, not operator-network data. Reported forecast, anomaly, and MTTR results will be generated from saved runs; no values are pre-claimed.

## Delivery target

Delivery window: 15–20 November 2026.

GCP deployment is required final-stage work. Local Linux validation comes first because Containerlab needs Linux networking; Terraform then deploys the runnable system to a GCP Compute Engine Linux VM. GCP project ID, billing approval, and credentials stay outside this repository.

## Prerequisites

- Python 3.11 or 3.12 for project dependencies
- Linux host or Linux VM for Containerlab execution
- Docker and Docker Compose (used from Task 2 onward)
- Terraform 1.9+ and a GCP project with an approved budget for Task 11 deployment

## Foundation setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
make check
```

`NETPULSE_DRY_RUN=true` is default. Do not put GCP credentials, Terraform variables, Grafana state, fault captures, or remediation audit logs in Git.

## Telemetry contract

Each FRR router has fixed management IP (`172.20.20.11`–`172.20.20.14`). Task 4 starts a small exporter sidecar in each router network namespace. Exporter reads only listed data-plane interface counters from `/sys/class/net`, exposes port `9100`, and never executes router commands.

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
make monitoring-down
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

After `make topology-up` and a successful `make topology-check`, run `make monitoring-up`.
Compose starts Prometheus, Grafana, Alertmanager, detector, guarded remediation API, and one
read-only metrics exporter in each router network namespace. Containerlab remains owned by
the topology targets; `make monitoring-down` does not destroy it. Grafana is available only
on `http://127.0.0.1:3000` and is declaratively provisioned with the NetPulse Prometheus
datasource and Link Overview dashboard. Default local credentials are `admin` /
`netpulse-local-only`; set `GRAFANA_ADMIN_PASSWORD` in `.env` before exposing the stack.

The devcontainer runs as `root`, is privileged, and mounts Docker runtime paths plus your Docker Desktop socket. Docker Desktop does not expose `/run/docker/netns`, so that native-Linux-only mount is intentionally omitted. Open this only for the trusted repository: it can control Docker Desktop containers and networks.

Terraform defines a single labelled Compute Engine VM, a dedicated VPC/subnet, and an SSH firewall
restricted to your `admin_cidr`. It has no committed project ID, credentials, local state, billing
configuration, or VM service-account attachment. Grafana remains loopback-only and is accessed over
an SSH tunnel. Run `make terraform-fmt` and `make terraform-validate` locally, then follow the
reviewed [GCP deployment guide](docs/gcp-deployment.md) before any `plan` or `apply`. See the
[foundation plan](docs/plans/netpulse-foundation-plan.md) for ordered acceptance criteria.

## Traffic and faults

Task 5 provides a deterministic 24-bucket compressed-day UDP traffic plan and an allow-listed
diamond-link fault scenario. Both commands are dry-run by default. The topology target builds
the local traffic-host image with `iperf3` before deployment.

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

The committed report is source-backed by that run, but remains a short synthetic experiment—not
an operator-network performance claim.

## Guarded remediation

Alertmanager sends `NetPulseLinkAnomaly` alerts to the local FastAPI remediation webhook. The
service accepts only the fixed OSPF link allow-list (`r1-r2`, `r1-r3`, `r2-r4`, and `r3-r4`),
serializes decisions, applies a monotonic per-interface cooldown, and appends audit JSONL records.
Its Prometheus endpoint exports remediation status counters and last-action latency.

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

## Planned architecture

```text
traffic + faults -> Containerlab/FRR -> Prometheus -> Grafana
                                      -> detector -> Alertmanager -> FastAPI remediation
                                                                    -> audit + MTTR results
```

## Safety and data boundary

- Keep auto-remediation dry-run until controlled live reroute test.
- Allow-list router/interface targets; record every decision in audit logs.
- Test future-time prediction with rolling-origin splits. Report leave-one-link-out transfer separately.
- Destroy GCP resources after demo unless explicitly retained.
