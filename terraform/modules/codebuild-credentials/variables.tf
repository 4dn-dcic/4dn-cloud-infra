variable "github_token" {
  description = "Sensitive create-only token. Requires hardened encrypted state. Adopt existing credential first; never commit real values."
  type        = string
  sensitive   = true
  nullable    = false
}
