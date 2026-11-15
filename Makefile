PYTHON ?= python3

.DEFAULT_GOAL := help
TRAFFIC_HOST_IMAGE := netpulse-traffic-host:0.1.0

.PHONY: help test lint format check topology-up topology-down topology-check traffic-host-image monitoring-up monitoring-live-up monitoring-down monitoring-config terraform-fmt terraform-init terraform-validate

help: ## Show currently available foundation commands.
	@awk 'BEGIN {FS = ":.*##"}; /^[a-zA-Z_-]+:.*##/ {printf "%-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

test: ## Run task-level repository tests.
	$(PYTHON) -m unittest discover -s tests -v

lint: ## Run Ruff after development dependencies are installed.
	$(PYTHON) -m ruff check .

format: ## Apply Ruff formatting after development dependencies are installed.
	$(PYTHON) -m ruff format .

check: test lint ## Run available automated checks.

traffic-host-image: ## Build the pinned Linux host image with iperf3.
	docker build --tag $(TRAFFIC_HOST_IMAGE) --file traffic/host.Dockerfile .

topology-up: traffic-host-image ## Deploy FRR diamond topology on Linux host.
	containerlab deploy -t topology/netpulse.clab.yml

topology-down: ## Destroy FRR topology and generated lab state.
	containerlab destroy --cleanup -t topology/netpulse.clab.yml

topology-check: ## Check OSPF adjacencies and r1 ECMP path.
	$(PYTHON) scripts/check_topology.py

monitoring-up: ## Start monitoring services after topology-up completes.
	docker compose up --build --detach

monitoring-live-up: ## Start explicit live-remediation override; both safety flags stay required.
	docker compose -f docker-compose.yml -f docker-compose.live.yml up --build --detach

monitoring-down: ## Stop monitoring services without changing the Containerlab topology.
	docker compose down

monitoring-config: ## Validate the Compose monitoring-stack configuration.
	docker compose config --quiet

terraform-fmt: ## Check Terraform formatting without contacting GCP.
	terraform -chdir=infra/terraform fmt -check

terraform-init: ## Download the pinned Terraform provider; no GCP resources are created.
	terraform -chdir=infra/terraform init -backend=false

terraform-validate: terraform-init ## Validate Terraform syntax and provider schema without credentials.
	terraform -chdir=infra/terraform validate
