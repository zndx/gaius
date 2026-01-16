# Gaius Web Infrastructure Variables

variable "cloudflare_account_id" {
  description = "Cloudflare account ID"
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for zndx.org"
  type        = string
}

variable "zone_name" {
  description = "DNS zone name"
  type        = string
  default     = "zndx.org"
}

variable "subdomain" {
  description = "Subdomain for the worker"
  type        = string
  default     = "gaius"
}

variable "worker_name" {
  description = "Name of the Cloudflare Worker"
  type        = string
  default     = "gaius-web"
}
