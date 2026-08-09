# Generate backend/cloudrun.env.yaml — the NON-SECRET Cloud Run config, built
# from .env with the secret keys stripped out (those come from Secret Manager
# at deploy time). COMMIT the generated file; the CI/CD workflow passes it to
# `gcloud run deploy --env-vars-file`. Re-run whenever non-secret config
# changes. Run from the backend/ directory:
#
#     ./gen-cloudrun-env.ps1
#
# Review the output before committing — anything in .env that isn't a known
# secret lands in this file.

param(
    [string]$EnvFile   = ".env",
    [string]$OutFile   = "cloudrun.env.yaml",
    [string]$ProjectId = "project-c9782021-0683-4eb3-88b"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $EnvFile)) { throw "$EnvFile not found. Run from the backend/ directory." }

# These live in Secret Manager and must never enter the committed config.
$SecretKeys = @("MONGO_URI","PYQ_MONGO_URI","JWT_SECRET_KEY","JWT_REFRESH_SECRET_KEY","BREVO_API_KEY","SMTP_PASSWORD","UPSTASH_REDIS_REST_URL","UPSTASH_REDIS_REST_TOKEN")


$out = New-Object System.Collections.Generic.List[string]
foreach ($line in Get-Content $EnvFile) {
    $trimmed = $line.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { continue }
    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()
    if ($SecretKeys -contains $key) { continue }
    if ($key -eq "PORT") { continue }                 # Cloud Run injects PORT itself
    if ($key -eq "APP_ENV") { $val = "production" }   # force prod regardless of .env
    $escaped = $val.Replace("\", "\\").Replace('"', '\"')
    $out.Add("${key}: `"$escaped`"")
}
if (-not ($out | Where-Object { $_ -like "GCP_PROJECT_ID:*" })) {
    $out.Add("GCP_PROJECT_ID: `"$ProjectId`"")
}

$outPath = Join-Path (Get-Location).Path $OutFile
[System.IO.File]::WriteAllLines($outPath, $out, (New-Object System.Text.UTF8Encoding $false))
Write-Host "Wrote $($out.Count) non-secret vars to $OutFile"
Write-Host "Review it, then commit: git add $OutFile"
