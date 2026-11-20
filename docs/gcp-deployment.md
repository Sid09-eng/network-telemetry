# GCP deployment reference

The Terraform profile creates one Ubuntu 24.04 VM, a dedicated VPC/subnet, and SSH restricted to
`admin_cidr`. The monitoring services remain loopback-only; no application port is publicly
exposed and no VM service account is attached. Cloud Monitoring manages two VM-level policies:
missing CPU telemetry for five minutes and CPU utilisation above the configured threshold for ten
minutes.

## Configuration

Create `infra/terraform/terraform.tfvars` from the example with the approved project ID, numeric
project number, billing account ID, region, zone, budget amount and currency, and a `/32` administrator
CIDR. `budget_currency_code` must match the billing account currency (for example, `INR` for an INR
account); it is not necessarily the VM region's currency. The project number is visible in the Google
Cloud Console project details. Keep that file, Terraform
state, plans, and credentials out of Git. Terraform creates a project-scoped monthly budget with
50%, 90%, and forecasted-100% thresholds, and enables the Billing Budgets API before creating the
budget. A budget sends alerts but does not stop resources automatically.

Authenticate the local Terraform client with `gcloud auth login` and
`gcloud auth application-default login` before planning. The VM itself uses no service account.
Before the first Terraform apply in a project, enable the Google Cloud Resource Manager API. The
Google provider needs it to manage the Billing Budgets API; Terraform then enables that API and
creates the budget itself.

```bash
gcloud services enable cloudresourcemanager.googleapis.com --project YOUR_PROJECT_ID
```

Your account needs permission to enable project services and create budgets. This one-time bootstrap
does not create a VM or alter the network.

`alert_notification_email` is optional. When set, Terraform creates an email notification channel;
the recipient must confirm Google's verification email before it receives policy notifications.
Leaving it `null` retains alert incidents in Cloud Monitoring without sending email. These are VM
health signals only: NetPulse services stay loopback-only and are not exposed to an external uptime
probe.

## Validate and apply

```bash
make terraform-fmt
make terraform-validate
terraform -chdir=infra/terraform plan -out=tfplan
```

Review the plan for the expected VM, subnet, restricted SSH rule, and no service account.

```bash
terraform -chdir=infra/terraform apply tfplan
terraform -chdir=infra/terraform output -raw ssh_command
```

The startup script installs Docker, Containerlab 0.83.0, and base tooling in `/opt/netpulse`.
Clone the repository to `/opt/netpulse/app` after the VM is available:

```bash
sudo git clone https://github.com/Sid09-eng/network-telemetry.git /opt/netpulse/app
cd /opt/netpulse/app
sudo cp .env.example .env
sudoedit .env
# Set GRAFANA_ADMIN_PASSWORD to a unique local value before continuing.
sudo make topology-up
sudo make topology-check
sudo make monitoring-up
```

Access Grafana through the generated SSH tunnel at `http://127.0.0.1:3000`:

```bash
terraform -chdir=infra/terraform output -raw grafana_tunnel_command
```

## Teardown

Remove the Terraform-managed VM, network, subnet, and firewall when the environment is no longer
needed:

```bash
terraform -chdir=infra/terraform destroy
```

Confirm the resources are gone in the GCP console. Billing alerts are a cost signal, not proof of
zero final charges.
