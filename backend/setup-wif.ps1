# Connect the GitHub repo to the deployer service account via Workload Identity
# Federation, so GitHub Actions authenticates to GCP with NO downloaded key.
# Run authenticated as the project owner:
#
#     ./setup-wif.ps1
#
# Safe to re-run: the pool/provider are created only if missing and the SA
# binding is idempotent. Prints the two values you paste into GitHub at the end.

param(
    [string]$ProjectId  = "project-c9782021-0683-4eb3-88b",
    [string]$DeployerId = "github-deployer",
    [string]$Repo       = "makemymock/makemymock-client",
    [string]$PoolId     = "github-pool",
    [string]$ProviderId = "github-provider"
)

$ErrorActionPreference = "Stop"
$DeployerSA = "$DeployerId@$ProjectId.iam.gserviceaccount.com"

# Federated principals are addressed by project NUMBER, not ID.
$ProjectNumber = gcloud projects describe $ProjectId --format="value(projectNumber)"
if ($LASTEXITCODE -ne 0 -or -not $ProjectNumber) { throw "Could not read project number." }

Write-Host "Enabling STS + IAM Credentials APIs ..."
gcloud services enable iamcredentials.googleapis.com sts.googleapis.com --project $ProjectId
if ($LASTEXITCODE -ne 0) { throw "Could not enable required APIs." }

# --- 1. Workload Identity Pool --------------------------------------------
$eap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
gcloud iam workload-identity-pools describe $PoolId --location=global --project $ProjectId 1>$null 2>$null
$poolExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $eap
if (-not $poolExists) {
    Write-Host "Creating pool $PoolId ..."
    gcloud iam workload-identity-pools create $PoolId `
        --location=global --display-name="GitHub Actions pool" --project $ProjectId
    if ($LASTEXITCODE -ne 0) { throw "Could not create the pool." }
} else {
    Write-Host "Pool $PoolId already exists."
}

# --- 2. OIDC Provider (trusts GitHub, locked to this one repo) -------------
$eap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
gcloud iam workload-identity-pools providers describe $ProviderId `
    --location=global --workload-identity-pool=$PoolId --project $ProjectId 1>$null 2>$null
$provExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $eap
if (-not $provExists) {
    Write-Host "Creating provider $ProviderId ..."
    gcloud iam workload-identity-pools providers create-oidc $ProviderId `
        --location=global `
        --workload-identity-pool=$PoolId `
        --display-name="GitHub OIDC" `
        --issuer-uri="https://token.actions.githubusercontent.com" `
        --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" `
        --attribute-condition="assertion.repository == '$Repo'" `
        --project $ProjectId
    if ($LASTEXITCODE -ne 0) { throw "Could not create the provider." }
} else {
    Write-Host "Provider $ProviderId already exists."
}

# --- 3. Let tokens from this repo impersonate the deployer SA --------------
Write-Host "Binding the deployer SA to the repo's federated identity ..."
$principal = "principalSet://iam.googleapis.com/projects/$ProjectNumber/locations/global/workloadIdentityPools/$PoolId/attribute.repository/$Repo"
gcloud iam service-accounts add-iam-policy-binding $DeployerSA `
    --role="roles/iam.workloadIdentityUser" `
    --member="$principal" --project $ProjectId | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not bind the deployer SA." }

# --- 4. Print the values GitHub needs -------------------------------------
$providerName = gcloud iam workload-identity-pools providers describe $ProviderId `
    --location=global --workload-identity-pool=$PoolId `
    --format="value(name)" --project $ProjectId

Write-Host ""
Write-Host "===== Add these in GitHub: repo -> Settings -> Secrets and variables -> Actions -> Variables ====="
Write-Host "WIF_PROVIDER = $providerName"
Write-Host "DEPLOYER_SA  = $DeployerSA"
