variable "project_id" {
  description = "Google Cloud-prosjektet som bare brukes av Bokbuzz."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry, hemmeligheter og bøtte. Må være i EU."
  type        = string
  default     = "europe-west4"

  validation {
    condition     = startswith(var.region, "europe-") && var.region != "europe-west2" && var.region != "europe-west6"
    error_message = "Velg en region i EU/EØS (ikke London eller Zürich)."
  }
}

variable "github_repository" {
  description = "Repoet som får deploye via Workload Identity Federation (ingen nøkler)."
  type        = string
  default     = "BokBuzz/Regnskapsagent"
}

variable "supabase_url" {
  description = "Supabase-prosjektets URL, brukes til å hente nøkler for innloggingstokens (JWKS)."
  type        = string
  default     = "https://ihmjkupqpgixmnguixds.supabase.co"
}

variable "documents_bucket_name" {
  description = "Globalt unikt navn på bøtta for originalbilag, f.eks. <prosjekt>-bilag."
  type        = string
}

variable "documents_retention_days" {
  description = "Oppbevaringstid for originalbilag. 5 år etter regnskapsårets slutt gir inntil ca. 6 år; verifiser med regnskapsfører."
  type        = number
  default     = 2192 # 6 år
}

variable "lock_documents_retention" {
  description = "Lås oppbevaringsregelen (Bucket Lock). KAN IKKE ANGRES. Sett til true først når regnskapsfører har bekreftet fristen."
  type        = bool
  default     = false
}

variable "image" {
  description = "Første containerbilde. Senere bilder settes av deploy-workflowen."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "model_default" {
  type    = string
  default = "gemini-3.1-flash-lite"
}

variable "model_escalation" {
  type    = string
  default = "gemini-3.8-flash"
}

variable "ai_monthly_cap_usd" {
  description = "Kostnadstak for KI per selskap og måned."
  type        = number
  default     = 5
}

variable "api_max_instances" {
  type    = number
  default = 3
}
