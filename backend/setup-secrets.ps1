# Create the MakeMyMock backend secrets in Google Secret Manager.
#
# Reads the sensitive values from backend/.env, stores each in Secret Manager,
# and grants the Cloud Run runtime service account read access. The CI/CD
# deploy later injects these with --set-secrets, so they never live in the
# workflow, the image, or a deploy log. Run from the backend/ directory:
#
#     ./setup-secrets.ps1
#
# Prereq: gcloud auth login (account that owns the project). This script
# enables the Secret Manager API itself. Safe to re-run — an existing secret
# just gets a fresh version, and the IAM grant is idempotent.

param(
    [string]$ProjectId      = "project-c9782021-0683-4eb3-88b",
    [string]$ServiceAccount = "makemymock-run@project-c9782021-0683-4eb3-88b.iam.gserviceaccount.com",
    [string]$EnvFile        = ".env",
    [string[]]$Secrets      = @("MONGO_URI","PYQ_MONGO_URI","JWT_SECRET_KEY","JWT_REFRESH_SECRET_KEY","BREVO_API_KEY","SMTP_PASSWORD","UPSTASH_REDIS_REST_URL","UPSTASH_REDIS_REST_TOKEN")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) { throw "$EnvFile not found. Run from the backend/ directory." }

Write-Host "Enabling Secret Manager API ..."
gcloud services enable secretmanager.googleapis.com --project $ProjectId
if ($LASTEXITCODE -ne 0) { throw "Could not enable secretmanager.googleapis.com." }

# Parse .env the same way deploy.ps1 does.
$envMap = @{}
foreach ($line in Get-Content $EnvFile) {
    $trimmed = $line.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { continue }
    $envMap[$line.Substring(0, $idx).Trim()] = $line.Substring($idx + 1).Trim()
}

$done = 0; $skipped = 0
foreach ($name in $Secrets) {
    $val = $envMap[$name]
    if ([string]::IsNullOrEmpty($val)) { Write-Host "skip  $name (not set in $EnvFile)"; $skipped++; continue }

    # Exact bytes only: UTF-8, no BOM, no trailing newline. A stray newline or
    # BOM would silently corrupt MONGO_URI / a JWT key and break auth.
    $tmp = New-TemporaryFile
    $tmpPath = $tmp.FullName
    [System.IO.File]::WriteAllText($tmpPath, $val, (New-Object System.Text.UTF8Encoding $false))

    # Create the container only if missing. Check via exit code, not by
    # scraping list output — exit codes don't lie about CRLF or formatting.
    $eap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
    gcloud secrets describe $name --project $ProjectId 1>$null 2>$null
    $secretExists = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $eap

    if (-not $secretExists) {
        gcloud secrets create $name --replication-policy=automatic --project $ProjectId
        if ($LASTEXITCODE -ne 0) { Remove-Item $tmpPath -Force; throw "create $name failed." }
    }

    gcloud secrets versions add $name --data-file="$tmpPath" --project $ProjectId
    if ($LASTEXITCODE -ne 0) { Remove-Item $tmpPath -Force; throw "versions add $name failed." }

    gcloud secrets add-iam-policy-binding $name `
        --member="serviceAccount:$ServiceAccount" `
        --role="roles/secretmanager.secretAccessor" `
        --project $ProjectId | Out-Null
    if ($LASTEXITCODE -ne 0) { Remove-Item $tmpPath -Force; throw "IAM grant on $name failed." }

    Remove-Item $tmpPath -Force
    Write-Host "set   $name"
    $done++
}

Write-Host ""
Write-Host "Done: $done secret(s) set, $skipped skipped."
Write-Host "Current secrets in ${ProjectId}:"
gcloud secrets list --project $ProjectId
