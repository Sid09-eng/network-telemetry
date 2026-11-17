provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

resource "google_compute_network" "netpulse" {
  name                    = "netpulse"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "netpulse" {
  name          = "netpulse"
  region        = var.region
  network       = google_compute_network.netpulse.id
  ip_cidr_range = "10.20.0.0/24"
}

resource "google_compute_firewall" "ssh" {
  name          = "netpulse-ssh"
  description   = "Permit SSH only from the approved operator CIDR."
  network       = google_compute_network.netpulse.name
  direction     = "INGRESS"
  source_ranges = [var.admin_cidr]
  target_tags   = ["netpulse"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_instance" "netpulse" {
  name         = var.instance_name
  machine_type = var.machine_type
  zone         = var.zone
  tags         = ["netpulse"]
  labels = merge(var.labels, {
    app        = "netpulse"
    managed_by = "terraform"
  })

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size  = 40
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.netpulse.id

    access_config {}
  }

  # Omitting this block attaches the project's default Compute Engine service account.
  # NetPulse needs no Google API identity, so request no service account explicitly.
  service_account {
    email  = null
    scopes = []
  }

  metadata_startup_script = file("${path.module}/startup.sh")

  # Metadata startup scripts run only during boot. Updating their source must not
  # replace an already-validated VM; recreate intentionally to consume a new script.
  lifecycle {
    ignore_changes = [metadata_startup_script]
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
}

locals {
  netpulse_instance_metric_filter = join(" AND ", [
    "metric.type = \"compute.googleapis.com/instance/cpu/utilization\"",
    "resource.type = \"gce_instance\"",
    "resource.label.\"instance_id\" = \"${google_compute_instance.netpulse.instance_id}\"",
  ])
  alert_notification_channels = google_monitoring_notification_channel.operator[*].name
}

# Email delivery is optional: a policy without a channel remains visible in Cloud Monitoring,
# while a configured address must be confirmed by the recipient before Google sends notifications.
resource "google_monitoring_notification_channel" "operator" {
  count = var.alert_notification_email == null ? 0 : 1

  display_name = "NetPulse operator email"
  type         = "email"
  labels = {
    email_address = var.alert_notification_email
  }
}

resource "google_monitoring_alert_policy" "vm_unavailable" {
  display_name          = "NetPulse VM telemetry absent"
  combiner              = "OR"
  enabled               = true
  notification_channels = local.alert_notification_channels
  user_labels = {
    app        = "netpulse"
    managed_by = "terraform"
  }

  documentation {
    mime_type = "text/markdown"
    content   = "Compute Engine has not emitted NetPulse VM CPU telemetry for five minutes. Check VM status and Cloud Monitoring metric ingestion."
  }

  conditions {
    display_name = "No VM CPU telemetry for five minutes"

    condition_absent {
      filter   = local.netpulse_instance_metric_filter
      duration = "300s"

      trigger {
        count = 1
      }
    }
  }
}

resource "google_monitoring_alert_policy" "cpu_saturation" {
  display_name          = "NetPulse VM CPU saturation"
  combiner              = "OR"
  enabled               = true
  notification_channels = local.alert_notification_channels
  user_labels = {
    app        = "netpulse"
    managed_by = "terraform"
  }

  documentation {
    mime_type = "text/markdown"
    content   = "NetPulse VM CPU utilisation exceeded the configured threshold for ten minutes. Inspect the local monitoring stack and VM workload."
  }

  conditions {
    display_name = "VM CPU utilisation above threshold for ten minutes"

    condition_threshold {
      filter          = local.netpulse_instance_metric_filter
      duration        = "600s"
      comparison      = "COMPARISON_GT"
      threshold_value = var.cpu_utilization_alert_threshold

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }

      trigger {
        count = 1
      }
    }
  }
}
