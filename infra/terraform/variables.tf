variable "project_id" {
  description = "Existing GCP project ID. It is intentionally not committed."
  type        = string
}

variable "project_number" {
  description = "Numeric GCP project number used by the billing-budget filter."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.project_number))
    error_message = "project_number must contain digits only."
  }
}

variable "billing_account_id" {
  description = "Billing account ID that owns the project and receives the NetPulse budget."
  type        = string

  validation {
    condition     = can(regex("^[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}$", var.billing_account_id))
    error_message = "billing_account_id must use the XXXXXX-XXXXXX-XXXXXX format."
  }
}

variable "budget_amount" {
  description = "Monthly NetPulse budget amount in the billing account's currency; this alerts but cannot stop spend."
  type        = number
  default     = 20

  validation {
    condition     = var.budget_amount > 0 && floor(var.budget_amount) == var.budget_amount
    error_message = "budget_amount must be a positive whole number."
  }
}

variable "budget_currency_code" {
  description = "Three-letter ISO currency code matching the attached billing account."
  type        = string
  default     = "USD"

  validation {
    condition     = can(regex("^[A-Z]{3}$", var.budget_currency_code))
    error_message = "budget_currency_code must be a three-letter uppercase ISO currency code."
  }
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
