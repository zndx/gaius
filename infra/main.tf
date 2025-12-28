# Gaius Web Infrastructure
#
# Cloudflare Workers deployment for gaius.zndx.org
#
# NOTE: Custom domain routing is handled by wrangler.toml, not terraform.
# This file manages supporting resources (KV, etc.)
#
# Deploy with: tofu init && tofu apply

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

provider "cloudflare" {
  # API token from CLOUDFLARE_API_TOKEN env var
}

# Workers KV namespace for session storage (future use)
resource "cloudflare_workers_kv_namespace" "gaius_sessions" {
  account_id = var.cloudflare_account_id
  title      = "gaius-sessions"
}

# Output the worker URL
output "worker_url" {
  description = "URL for the Gaius web worker"
  value       = "https://${var.subdomain}.${var.zone_name}"
}

output "callback_url" {
  description = "OAuth callback URL for X API"
  value       = "https://${var.subdomain}.${var.zone_name}/x-callback"
}
