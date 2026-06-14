# Deploy the MakeMyMock backend to Google Cloud Run.
#
# Reads backend/.env, turns it into a Cloud Run env-vars YAML (so values with
# commas/@ — like MONGO_URI — survive intact), builds the image with Cloud
# Build, and deploys. Run from the backend/ directory:
#
#     ./deploy.ps1
#
# Prereqs (one-time — see the deploy notes):
#   * gcloud auth login   (account that owns the project)
#   * APIs enabled: run, cloudbuild, artifactregistry, aiplatform
#   * Artifact Registry repo created
#   * runtime service account created with roles/aiplatform.user
#
# Override any default with a flag, e.g.  ./deploy.ps1 -Region us-central1

param(
    [string]$ProjectId   = "project-c9782021-0683-4eb3-88b",
    [string]$Region      = "asia-south1",
    [string]$Service     = "makemymock-backend",
    [string]$Repo        = "makemymock",
    [string]$ServiceAccount = "makemymock-run@project-c9782021-0683-4eb3-88b.iam.gserviceaccount.com",
    [string]$EnvFile     = ".env"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) { throw "$EnvFile not found. Run from the backend/ directory." }

$image = "$Region-docker.pkg.dev/$ProjectId/$Repo/backend:latest"
$envYaml = Join-Path $env:TEMP "mmm-cloudrun-env.yaml"

# --- 1. Build a Cloud Run env-vars YAML from .env -------------------------
# YAML string-escapes each value, so commas, @, : etc. are preserved verbatim.
$lines = Get-Content $EnvFile
$yaml = New-Object System.Collections.Generic.List[string]
foreach ($line in $lines) {
    $trimmed = $line.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { continue }
    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()
    # Force production env regardless of what the local file says.
    if ($key -eq "APP_ENV") { $val = "production" }
    # Cloud Run injects PORT itself; never override it.
    if ($key -eq "PORT") { continue }
    $escaped = $val.Replace("\", "\\").Replace('"', '\"')
    $yaml.Add("${key}: `"$escaped`"")
}
# Make sure Vertex points at this project even if .env lagged behind.
if (-not ($yaml | Where-Object { $_ -like "GCP_PROJECT_ID:*" })) {
    $yaml.Add("GCP_PROJECT_ID: `"$ProjectId`"")
}
$yaml | Set-Content -Path $envYaml -Encoding utf8
Write-Host "Wrote $($yaml.Count) env vars to $envYaml"

# --- 2. Build + push the image with Cloud Build ---------------------------
Write-Host "`nBuilding image $image ..."
gcloud builds submit --tag $image --project $ProjectId
if ($LASTEXITCODE -ne 0) { throw "Cloud Build failed." }

# --- 3. Deploy to Cloud Run -----------------------------------------------
Write-Host "`nDeploying to Cloud Run ..."
gcloud run deploy $Service `
    --image $image `
    --project $ProjectId `
    --region $Region `
    --service-account $ServiceAccount `
    --env-vars-file $envYaml `
    --allow-unauthenticated `
    --port 8080 `
    --cpu 1 --memory 512Mi `
    --min-instances 0 --max-instances 5 `
    --timeout 300
if ($LASTEXITCODE -ne 0) { throw "Cloud Run deploy failed." }

# --- 4. Cleanup + report --------------------------------------------------
Remove-Item $envYaml -Force
$url = gcloud run services describe $Service --project $ProjectId --region $Region --format "value(status.url)"
Write-Host "`nDeployed: $url"
Write-Host "Health:   $url/health"
Write-Host "Docs:     $url/docs"
