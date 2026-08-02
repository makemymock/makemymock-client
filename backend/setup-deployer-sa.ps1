# Create the GitHub Actions deployer service account for the backend CI/CD
# pipeline and grant it the minimum roles to build + deploy.
#
# This is the identity GitHub authenticates as (keyless, via Workload Identity
# Federation — set up separately). It can push images and roll out Cloud Run
# revisions, but has NO access to the database, secrets, or Vertex. Run it
# authenticated as the project owner:
#
#     ./setup-deployer-sa.ps1
#
# Safe to re-run: the SA is created only if missing, and the role bindings are
# idempotent.

param(
    [string]$ProjectId  = "project-c9782021-0683-4eb3-88b",
    [string]$RuntimeSA  = "makemymock-run@project-c9782021-0683-4eb3-88b.iam.gserviceaccount.com",
    [string]$DeployerId = "github-deployer"
)

$ErrorActionPreference = "Stop"
$DeployerSA = "$DeployerId@$ProjectId.iam.gserviceaccount.com"

# --- 1. Create the deployer SA if it doesn't exist yet ---------------------
$eap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
gcloud iam service-accounts describe $DeployerSA --project $ProjectId 1>$null 2>$null
$saExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $eap

if (-not $saExists) {
    Write-Host "Creating $DeployerSA ..."
    gcloud iam service-accounts create $DeployerId `
        --display-name="GitHub Actions deployer (CI/CD)" --project $ProjectId
    if ($LASTEXITCODE -ne 0) { throw "Could not create the deployer service account." }
    # A new SA identity takes a few seconds to propagate before IAM will
    # accept it as a binding member.
    Start-Sleep -Seconds 10
} else {
    Write-Host "$DeployerSA already exists."
}

# --- 2. Grant the minimum deploy roles ------------------------------------
Write-Host "Granting roles/run.admin ..."
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$DeployerSA" `
    --role="roles/run.admin" --condition=None | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to grant roles/run.admin." }

Write-Host "Granting roles/artifactregistry.writer ..."
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$DeployerSA" `
    --role="roles/artifactregistry.writer" --condition=None | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to grant roles/artifactregistry.writer." }

# Scoped to the runtime SA only: lets the deployer deploy Cloud Run AS it.
Write-Host "Granting roles/iam.serviceAccountUser on the runtime SA ..."
gcloud iam service-accounts add-iam-policy-binding $RuntimeSA `
    --member="serviceAccount:$DeployerSA" `
    --role="roles/iam.serviceAccountUser" --condition=None --project $ProjectId | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to grant roles/iam.serviceAccountUser on the runtime SA." }

# --- 3. Report ------------------------------------------------------------
Write-Host ""
Write-Host "Deployer SA ready: $DeployerSA"
Write-Host ""
Write-Host "Project-level roles:"
gcloud projects get-iam-policy $ProjectId `
    --flatten="bindings[].members" `
    --filter="bindings.members:$DeployerSA" `
    --format="table(bindings.role)"
Write-Host "serviceAccountUser on the runtime SA:"
gcloud iam service-accounts get-iam-policy $RuntimeSA --project $ProjectId `
    --flatten="bindings[].members" `
    --filter="bindings.members:$DeployerSA" `
    --format="table(bindings.role)"
