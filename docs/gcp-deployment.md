# GCP deployment and cost controls

Task 11 deploys one Ubuntu 24.04 Compute Engine VM for the NetPulse demonstration. It creates a
dedicated VPC/subnet, a VM, and one ingress rule: SSH is reachable only from `admin_cidr`. Grafana,
Prometheus, Alertmanager, detector, and remediation remain bound to VM loopback and are not exposed
to the internet; there is no `0.0.0.0/0` ingress rule.

## Before planning

1. Create or select a GCP project and enable billing. Do not put its ID, billing account, or
   credentials in this repository.
2. Enable the Compute Engine API in that project.
3. Authenticate Terraform using an approved local Application Default Credential or a
   least-privilege service account. Keep credential files outside the repository.
4. Copy the example and replace every placeholder with the approved values:

   ```bash
   cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
   ```

   Set `admin_cidr` to your current public IP with a `/32` suffix. Do not use a broad internet
   range merely to make the firewall work.

5. In Cloud Billing, create a budget for this project before applying. Use a small monthly amount,
   email alerts at 50%, 90%, and 100%, and label the project or VM for the demo. Budgets alert on
   spend; they do not automatically stop running resources, so teardown remains the operator's
   responsibility.

## Local checks and review

Run these commands before any cloud change:

```bash
make terraform-fmt
make terraform-validate
terraform -chdir=infra/terraform plan -out=tfplan
```

Read the plan and confirm it creates only the NetPulse network, subnet, one restricted firewall,
and one labelled VM without a Compute Engine service account. `plan`, `apply`, and state files can contain project identifiers, so do not
commit them.

## Apply and deploy the stack

Only after reviewing the plan and confirming the budget alert:

```bash
terraform -chdir=infra/terraform apply tfplan
terraform -chdir=infra/terraform output -raw ssh_command
```

The startup script installs signed Docker packages, pinned Containerlab `0.83.0`, and prepares
`/opt/netpulse`; it deliberately does not clone a repository or carry credentials. Use the SSH
output to copy or clone a reviewed checkout, then follow the repository's Linux topology and
monitoring instructions on the VM. To access Grafana, run this locally, keep the tunnel open, and
browse to `http://127.0.0.1:3000`:

```bash
terraform -chdir=infra/terraform output -raw grafana_tunnel_command
```

## Teardown and cost control

Stop the demo promptly and remove every Terraform-managed resource:

```bash
terraform -chdir=infra/terraform destroy
```

Confirm the instance, disks, VPC, and firewall rules are gone in the GCP console. Retain nothing
unless you explicitly choose to keep it and accept the ongoing cost. Review the billing budget
notifications after teardown; they are an alerting aid, not proof of zero final charges.
