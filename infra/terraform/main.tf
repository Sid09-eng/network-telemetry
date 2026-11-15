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
      image = "ubuntu-os-cloud/ubuntu-2404-lts"
      size  = 40
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.netpulse.id

    access_config {}
  }

  metadata_startup_script = file("${path.module}/startup.sh")

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
