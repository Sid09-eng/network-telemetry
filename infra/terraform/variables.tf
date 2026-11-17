variable "project_id" {
  description = "Existing GCP project ID. It is intentionally not committed."
  type        = string
}

variable "region" {
  description = "GCP region that contains the NetPulse VM."
  type        = string
}

variable "zone" {
  description = "GCP zone that contains the NetPulse VM."
  type        = string
}

variable "admin_cidr" {
  description = "Operator public IPv4 CIDR allowed to access SSH and NetPulse UI ports."
  type        = string

  validation {
    condition     = can(cidrhost(var.admin_cidr, 0))
    error_message = "admin_cidr must be a valid IPv4 or IPv6 CIDR, for example 203.0.113.10/32."
  }
}

variable "machine_type" {
  description = "Machine type for the demonstration VM."
  type        = string
  default     = "e2-medium"
}

variable "instance_name" {
  description = "Name of the Compute Engine VM."
  type        = string
  default     = "netpulse"
}

variable "labels" {
  description = "Additional cost-attribution labels. app and managed_by remain Terraform controlled."
  type        = map(string)
  default     = {}
}

variable "alert_notification_email" {
  description = "Optional email address for Cloud Monitoring notifications; the recipient must confirm it in GCP."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.alert_notification_email == null
      || can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.alert_notification_email))
    )
    error_message = "alert_notification_email must be a valid email address or null."
  }
}

variable "cpu_utilization_alert_threshold" {
  description = "CPU utilisation ratio that must be exceeded for ten minutes before an alert opens."
  type        = number
  default     = 0.90

  validation {
    condition     = var.cpu_utilization_alert_threshold > 0 && var.cpu_utilization_alert_threshold <= 1
    error_message = "cpu_utilization_alert_threshold must be greater than 0 and at most 1."
  }
}
