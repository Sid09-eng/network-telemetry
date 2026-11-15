output "instance_name" {
  value       = google_compute_instance.netpulse.name
  description = "Created Compute Engine instance name."
}

output "external_ip" {
  value       = google_compute_instance.netpulse.network_interface[0].access_config[0].nat_ip
  description = "Public IP restricted by admin_cidr firewall rules."
}

output "grafana_tunnel_command" {
  value       = "gcloud compute ssh ${google_compute_instance.netpulse.name} --project ${var.project_id} --zone ${var.zone} -- -N -L 3000:127.0.0.1:3000"
  description = "Keep this SSH tunnel open, then open http://127.0.0.1:3000 locally."
}

output "ssh_command" {
  value       = "gcloud compute ssh ${google_compute_instance.netpulse.name} --project ${var.project_id} --zone ${var.zone}"
  description = "Gcloud command for the operator with project access."
}
