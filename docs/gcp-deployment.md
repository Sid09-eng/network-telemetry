# GCP deployment reference

The Terraform profile creates one Ubuntu 24.04 VM, a dedicated VPC/subnet, and SSH restricted to
`admin_cidr`. The monitoring services remain loopback-only; no application port is publicly
exposed and no VM service account is attached.

## Configuration

Create `infra/terraform/terraform.tfvars` from the example with the approved project ID, region,
zone, and a `/32` administrator CIDR. Keep that file, Terraform state, plans, and credentials out
of Git. Enable Compute Engine and set a project budget before applying; a budget sends alerts but
does not stop resources automatically.

Terraform uses local Application Default Credentials; authenticate before planning with an account
that has only the GCP roles approved for this demonstration. Keep credential files outside this
checkout. `gcloud` must be installed and authenticated as the same operator before using the SSH
commands emitted by Terraform.

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project "<project-id>"
```

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
git clone https://github.com/Sid09-eng/network-telemetry.git /opt/netpulse/app
cd /opt/netpulse/app
sudo make topology-up
sudo make topology-check
sudo make monitoring-up
```

After the topology check and monitoring startup succeed, access Grafana through the generated SSH
tunnel at `http://127.0.0.1:3000`:

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
