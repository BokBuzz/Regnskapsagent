terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.10"
    }
  }

  # Tilstanden ligger i en egen bøtte som eier lager én gang (se docs/OPPSETT.md):
  #   terraform init -backend-config="bucket=<prosjekt>-tfstate"
  backend "gcs" {
    prefix = "bokbuzz"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
