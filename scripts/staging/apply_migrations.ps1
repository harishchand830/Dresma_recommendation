# Apply Spanner DDL migrations needed for heuristic staging (001-005).
# Run from repo root on your company laptop after filling .env / gcloud auth.
#
# Usage:
#   $env:SPANNER_INSTANCE_ID = "your-instance"
#   $env:SPANNER_DATABASE_ID = "your-database"
#   .\scripts\staging\apply_migrations.ps1
#
# Or pass explicitly:
#   .\scripts\staging\apply_migrations.ps1 -InstanceId "inst" -DatabaseId "db"

param(
    [string]$InstanceId = $env:SPANNER_INSTANCE_ID,
    [string]$DatabaseId = $env:SPANNER_DATABASE_ID
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $RepoRoot

if (-not $InstanceId -or -not $DatabaseId) {
    Write-Error "Set SPANNER_INSTANCE_ID and SPANNER_DATABASE_ID in .env or pass -InstanceId / -DatabaseId"
}

$Migrations = @(
    "002_image_signals.sql",
    "003_clusters.sql",
    "004_image_engagement_history.sql",
    "005_cluster_trends.sql",
    "012_brand_references_cluster.sql"
)

Write-Host "Applying $($Migrations.Count) Spanner migrations to $DatabaseId on $InstanceId ..." -ForegroundColor Cyan

foreach ($file in $Migrations) {
    $path = Join-Path "infra\spanner\migrations" $file
    if (-not (Test-Path $path)) {
        Write-Error "Missing migration file: $path"
    }
    Write-Host "`n>>> $file" -ForegroundColor Yellow
    gcloud spanner databases ddl update $DatabaseId `
        --instance=$InstanceId `
        --ddl-file=$path
    if ($LASTEXITCODE -ne 0) {
        Write-Error "DDL update failed for $file (exit $LASTEXITCODE). Already applied? Check Spanner console."
    }
}

Write-Host "`nMigrations applied. Next: python scripts/staging_first_time_setup.py" -ForegroundColor Green
