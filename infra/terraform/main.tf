locals {
  services = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ]
  repository_path = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.bokbuzz.repository_id}"
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Containerregister
# ---------------------------------------------------------------------------
resource "google_artifact_registry_repository" "bokbuzz" {
  location      = var.region
  repository_id = "bokbuzz"
  format        = "DOCKER"

  cleanup_policies {
    id     = "behold-siste-20"
    action = "KEEP"
    most_recent_versions {
      keep_count = 20
    }
  }
  cleanup_policies {
    id     = "slett-gamle"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 dager
    }
  }

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------------------
# Originalbilag: versjonert, ikke offentlig, med oppbevaringsregel (WORM når låst)
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "documents" {
  name                        = var.documents_bucket_name
  location                    = upper(var.region)
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = var.documents_retention_days * 86400
    is_locked        = var.lock_documents_retention
  }

  soft_delete_policy {
    retention_duration_seconds = 90 * 86400
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------------------
# Tjenestekontoer: én per komponent, minste nødvendige rettigheter
# ---------------------------------------------------------------------------
resource "google_service_account" "api" {
  account_id   = "bokbuzz-api"
  display_name = "Bokbuzz API (Cloud Run)"
}

resource "google_service_account" "worker" {
  account_id   = "bokbuzz-worker"
  display_name = "Bokbuzz jobbarbeider (Cloud Run)"
}

resource "google_service_account" "deployer" {
  account_id   = "bokbuzz-deployer"
  display_name = "Bokbuzz deploy fra GitHub Actions"
}

# API: lese og skrive nye objekter, aldri slette eller overskrive.
resource "google_storage_bucket_iam_member" "api_create" {
  bucket = google_storage_bucket.documents.name
  role   = "roles/storage.objectCreator"
  member = google_service_account.api.member
}

resource "google_storage_bucket_iam_member" "api_read" {
  bucket = google_storage_bucket.documents.name
  role   = "roles/storage.objectViewer"
  member = google_service_account.api.member
}

# Arbeider: lese bilag og kalle Vertex AI.
resource "google_storage_bucket_iam_member" "worker_read" {
  bucket = google_storage_bucket.documents.name
  role   = "roles/storage.objectViewer"
  member = google_service_account.worker.member
}

resource "google_project_iam_member" "worker_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = google_service_account.worker.member
}

# ---------------------------------------------------------------------------
# Hemmeligheter. Terraform lager bare «skallene»; verdiene legger eier inn selv,
# slik at passord aldri havner i Terraform-tilstanden.
# ---------------------------------------------------------------------------
resource "google_secret_manager_secret" "api_database_url" {
  secret_id = "bokbuzz-api-database-url"
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret" "worker_database_url" {
  secret_id = "bokbuzz-worker-database-url"
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_iam_member" "api_db" {
  secret_id = google_secret_manager_secret.api_database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.api.member
}

resource "google_secret_manager_secret_iam_member" "worker_db" {
  secret_id = google_secret_manager_secret.worker_database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.worker.member
}

# ---------------------------------------------------------------------------
# Cloud Run: API (offentlig, egen innlogging i appen) og arbeider (intern)
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "api" {
  name                = "bokbuzz-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true

  template {
    service_account = google_service_account.api.email
    scaling {
      min_instance_count = 0
      max_instance_count = var.api_max_instances
    }
    containers {
      image = var.image
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      env {
        name  = "BOKBUZZ_ENVIRONMENT"
        value = "prod"
      }
      env {
        name  = "BOKBUZZ_SUPABASE_URL"
        value = var.supabase_url
      }
      env {
        name  = "BOKBUZZ_STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "BOKBUZZ_GCS_BUCKET"
        value = google_storage_bucket.documents.name
      }
      env {
        name = "BOKBUZZ_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_database_url.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    # Bildet byttes av deploy-workflowen, ikke av Terraform.
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_iam_member.api_db]
}

# API-et sjekker selv Supabase-token og MFA, så Cloud Run må slippe alle inn.
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "worker" {
  name                = "bokbuzz-worker"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = true

  template {
    service_account = google_service_account.worker.email
    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }
    containers {
      image   = var.image
      command = ["python", "-m", "bokbuzz.worker"]
      resources {
        limits   = { cpu = "1", memory = "512Mi" }
        cpu_idle = false # jobbløkken må få CPU også uten forespørsler
      }
      env {
        name  = "BOKBUZZ_ENVIRONMENT"
        value = "prod"
      }
      env {
        name  = "BOKBUZZ_STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "BOKBUZZ_GCS_BUCKET"
        value = google_storage_bucket.documents.name
      }
      env {
        name  = "BOKBUZZ_AI_PROVIDER"
        value = "vertex"
      }
      env {
        name  = "BOKBUZZ_GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "BOKBUZZ_VERTEX_LOCATION"
        value = "eu"
      }
      env {
        name  = "BOKBUZZ_MODEL_DEFAULT"
        value = var.model_default
      }
      env {
        name  = "BOKBUZZ_MODEL_ESCALATION"
        value = var.model_escalation
      }
      env {
        name  = "BOKBUZZ_AI_MONTHLY_CAP_USD"
        value = tostring(var.ai_monthly_cap_usd)
      }
      env {
        name = "BOKBUZZ_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.worker_database_url.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_iam_member.worker_db]
}

# ---------------------------------------------------------------------------
# Deploy fra GitHub Actions uten nøkler (Workload Identity Federation),
# begrenset til main-grenen i Bokbuzz-repoet.
# ---------------------------------------------------------------------------
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.enabled]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "GitHub Actions OIDC"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/main'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_push" {
  location   = var.region
  repository = google_artifact_registry_repository.bokbuzz.name
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.deployer.member
}

resource "google_cloud_run_v2_service_iam_member" "deployer_api" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.developer"
  member   = google_service_account.deployer.member
}

resource "google_cloud_run_v2_service_iam_member" "deployer_worker" {
  name     = google_cloud_run_v2_service.worker.name
  location = var.region
  role     = "roles/run.developer"
  member   = google_service_account.deployer.member
}

# Deployeren må kunne starte tjenestene som API- og arbeiderkontoen.
resource "google_service_account_iam_member" "deployer_acts_as_api" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.deployer.member
}

resource "google_service_account_iam_member" "deployer_acts_as_worker" {
  service_account_id = google_service_account.worker.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.deployer.member
}
