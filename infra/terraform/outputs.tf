output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "artifact_repository" {
  description = "Settes som GitHub-variabelen GCP_ARTIFACT_REPO."
  value       = local.repository_path
}

output "workload_identity_provider" {
  description = "Settes som GitHub-variabelen GCP_WIF_PROVIDER."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  description = "Settes som GitHub-variabelen GCP_DEPLOYER_SA."
  value       = google_service_account.deployer.email
}

output "documents_bucket" {
  value = google_storage_bucket.documents.name
}
