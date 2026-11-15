output "instance_name" {
  value       = google_compute_instance.netpulse.name
  description = "Created Compute Engine instance name."
}

output "external_ip" {
  value       = google_compute_instance.netpulse.network_interface[0].access_config[0].nat_ip
  description = "Public IP restricted by admin_cidr firewall rules."
}

output "grafana_url" {
  value       = "http://${google_compute_instance.netpulse.network_interface[0].access_config[0].nat_ip}:3000"
  description = "Grafana URL after the NetPulse Compose stack has been deployed to the VM."
}

output "ssh_command" {
  value       = "gcloud compute ssh ${google_compute_instance.netpulse.name} --project ${var.project_id} --zone ${var.zone}"
  description = "Gcloud command for the operator with project access."
}
