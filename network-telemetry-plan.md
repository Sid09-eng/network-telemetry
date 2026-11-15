# Network Telemetry, Forecasting and Auto-Remediation: Build Plan

**Goal:** a GitHub project that shows cloud, DevOps and ML skills on a network-operations problem, ready before within **5 days**.
**Time available:** about 5 days (15 Nov to 20 Nov).
**Working name:** `netpulse` (rename as you like).

---

## 1. What you are building

A simulated network that produces real telemetry, a forecasting and anomaly-detection service that watches it, and a remediation service that fixes faults automatically. Everything runs from one `docker compose up` or Makefile command, and a cloud deployment is defined as code.

```
 traffic generator + fault injector
              |
              v
   Containerlab virtual network (FRR routers + hosts)
              |  interface counters (bytes, errors, drops)
              v
   node_exporter / exporters --> Prometheus --> Grafana dashboards
                                     |
                                     v
                       Forecast + anomaly service (Python)
                        - predicts next-interval link utilisation
                        - flags anomalies from forecast residuals
                                     |
                                     v
                              Alertmanager
                                     |  webhook
                                     v
                       Remediation service (FastAPI)
                        - reroutes via OSPF cost change (dry-run first)
                        - cooldown, rollback, audit log
                                     |
                                     v
                         MTTR + metrics written to results/
```

**Honest framing (put this in the README):** the network is simulated and the traffic is synthetic. Do not claim it represents a real operator's network.

---

## 2. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Virtual network | Containerlab + FRRouting (Docker images) | Free, reproducible, runs on a laptop or a Linux VM |
| Traffic | iperf3 plus a Python scheduler | Controllable daily pattern, noise and bursts |
| Fault injection | `tc netem` (loss, delay), `ip link set down` | Realistic, scriptable faults with known timestamps |
| Metrics | Prometheus + node_exporter in router containers | Standard monitoring stack |
| Dashboards | Grafana (provisioned from JSON files in the repo) | Looks good in a GIF |
| Forecasting | Python, pandas, scikit-learn | Reuses your FYP skills |
| Alerting | Alertmanager with a webhook receiver | Standard path from alert to action |
| Remediation | FastAPI service running `vtysh` commands in the routers | Shows closed-loop automation |
| Cloud | GCP Compute Engine VM, defined in Terraform | You already know GCP |
| CI | GitHub Actions | Lint, tests, image build, Terraform validation |

Stretch option: swap FRR for Nokia SR Linux and collect with gNMI (gnmic). Only try this if you finish early.

---

## 3. Repository structure

```
netpulse/
  README.md                  # GIF, problem, architecture diagram, results, limitations
  Makefile                   # make up / down / demo / test / eval
  docker-compose.yml         # Prometheus, Grafana, Alertmanager, services
  topology/
    netpulse.clab.yml        # Containerlab topology (4-6 routers, 2-3 hosts)
    configs/                 # FRR configs per router
  traffic/
    generate.py              # daily-pattern traffic scheduler
    faults.py                # fault injector, writes ground-truth fault log
  monitoring/
    prometheus.yml
    alert_rules.yml
    alertmanager.yml
    grafana/                 # provisioned dashboards and datasources
  forecast/
    features.py              # lags, rolling windows, time-of-day features
    train.py                 # models + baselines
    evaluate.py              # rolling-origin validation, writes results/
    detect.py                # residual-based anomaly detection
  remediation/
    app.py                   # FastAPI webhook receiver
    actions.py               # OSPF cost change, rollback, dry-run
    audit.log                # (gitignored) action history
  infra/
    terraform/               # GCP VM, firewall, budget alert
  tests/
  results/                   # metrics tables and plots committed for the README
  docs/
    architecture.png
    demo.gif
  .github/workflows/ci.yml
```

---

## 4. Timeline

### Stage 1: Network and telemetry
- Install Docker and Containerlab, and bring up a 4-router topology with OSPF and two hosts.
- Add node_exporter in each router's network namespace and scrape interface counters with Prometheus.
- Build one Grafana dashboard showing per-link throughput, errors and drops.
- Write `traffic/generate.py`: a sinusoidal daily pattern, random noise and occasional bursts, compressed so one "day" takes about 30 to 60 minutes.

**Done when:** `make up` starts everything, and Grafana shows live traffic that rises and falls on a schedule.

### Stage 2: Data collection and forecasting
- Run the simulation for several hours and export the metrics to Parquet or CSV (at least a few "days" of data).
- Write `traffic/faults.py` to inject faults at random times, and save a ground-truth log of fault start and end.
- Build features: lags, rolling mean and standard deviation, time-of-day sine and cosine.
- Models: persistence baseline, seasonal-naive baseline, Ridge, HistGradientBoosting.
- Validate with rolling-origin (time-ordered) splits so there is no leakage, and also hold out one link at a time.
- Report MAE and RMSE against the baselines in `results/forecast_metrics.md`.

**Done when:** you have a results table with at least one model beating persistence, or an honest note saying none did and why.

### Stage 3: Anomaly detection and remediation
- Anomaly detection: flag points where the forecast residual exceeds a threshold (rolling z-score). Evaluate against the ground-truth fault log: precision, recall and detection delay.
- Wire it to Prometheus and Alertmanager so detections fire an alert (push anomaly scores as a metric the rules can read).
- Build the remediation service. The first action is raising the OSPF cost on a congested or degraded link so traffic reroutes.
- Safety features: dry-run mode (default), cooldown timer, automatic rollback after recovery, audit log.
- Measure MTTR: fault start to traffic restored, with and without the remediation service.

**Done when:** a fault is injected, an alert fires, traffic reroutes automatically, and the MTTR comparison is saved to `results/`.

### Stage 4: Cloud, CI and polish

- Terraform for a GCP VM (Containerlab needs a Linux host with Docker). Include a firewall rule, a startup script that installs the dependencies, and a budget alert. Check current pricing first: the smallest free-tier VM may be too small, so use a modest machine and destroy it after the demo.
- GitHub Actions: lint (ruff), unit tests (pytest), Docker image builds, `terraform fmt` and `terraform validate`. Add a Containerlab smoke test only if it runs reliably.
- Record a 30-second GIF of the demo, draw the architecture diagram, and finish the README.

**Done when:** a stranger can clone the repo, run one command and see the demo.

### Buffer (7 Dec)
Rehearse the 2-minute explanation, test the setup from a clean clone and fix the README.

---

## 5. Cut lines if you fall behind

| If you are behind by | Drop |
|---|---|
| A few days | Terraform and the cloud deployment (describe the design in the README) |
| A week | Automatic rollback and the cooldown (keep dry-run and the audit log) |
| Two weeks | Machine-learning forecasting (use baselines plus the residual detector), but keep remediation |

The minimum project worth showing: virtual network, Prometheus and Grafana, fault injection, one alert and one automated fix with a measured recovery time.

---

## 6. Numbers to report in the README

Collect real numbers and state them plainly:
- Forecast MAE and RMSE versus the persistence and seasonal-naive baselines.
- Anomaly detection precision, recall and mean detection delay against injected faults.
- MTTR with and without auto-remediation.
- Test count and CI status badge.
- A limitations section: simulated data, small topology, single remediation action, no real devices.

---

## 7. README outline

1. One-line problem statement and a demo GIF.
2. Architecture diagram.
3. Quick start (`make up`, `make demo`).
4. How it works: telemetry, forecasting, detection, remediation.
5. Results table.
6. Design decisions (why dry-run, why rolling-origin validation).
7. Limitations and next steps.

---

## 8. CV bullets (fill in only with your real numbers)

- Built a simulated network (Containerlab, FRRouting) with Prometheus and Grafana telemetry, and a Docker-based pipeline that deploys to GCP with Terraform.
- Developed leakage-aware link-utilisation forecasting, reducing MAE by **[X]%** versus a persistence baseline, with anomaly detection reaching **[P] precision / [R] recall** on injected faults.
- Implemented automated remediation (alert to webhook to OSPF reroute) with dry-run, rollback and audit logging, cutting mean time to recovery from **[A] to [B]** seconds.
- Automated testing and builds with GitHub Actions (**[N]** tests).

---

## 9. Interview talking points

- Why you chose the problem: it combines the cloud, automation and "network intelligence" areas in the Singtel posting.
- The leakage story: explain how you validated the forecast without peeking at the future (links to your FYP and Essos).
- Safety in automation: why the default is dry-run and how rollback works.
- What you would do with real operator data and real devices.
- One thing that went wrong and how you fixed it.

---

## 10. Setup checklist

- [ ] Linux machine or VM with Docker (Containerlab does not run natively on macOS or Windows; use a Linux VM or WSL2)
- [ ] GCP project with a budget alert set before creating anything
- [ ] GitHub repo created, with an initial README and CI skeleton
- [ ] Decide the "compressed day" length for the traffic simulation
