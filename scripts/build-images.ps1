# Build all container images for the Dynamic Pricing MAB stack.
#
# This script works around the podman-compose `dockerfile:` bug (see
# podman-compose.yml header) by pre-building all images with explicit
# `-f` flags, which podman handles correctly. After running this script,
# `podman-compose up` will find the images by name and skip building.
#
# Usage:
#   cd c:\hackathon\dynamic-pricing-MAB
#   .\scripts\build-images.ps1
#
# Then:
#   podman-compose up

$ErrorActionPreference = "Stop"

Write-Host "=== Building Dynamic Pricing MAB images ===" -ForegroundColor Cyan
Write-Host ""

# Ensure we're in the project root
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "[1/4] Building pricing-bootstrap (trainer)..." -ForegroundColor Yellow
podman build -f Dockerfile.trainer -t localhost/pricing-bootstrap .
if ($LASTEXITCODE -ne 0) { throw "Failed to build pricing-bootstrap" }

Write-Host "[2/4] Building pricing-api..." -ForegroundColor Yellow
podman build -f Dockerfile.api -t localhost/pricing-api .
if ($LASTEXITCODE -ne 0) { throw "Failed to build pricing-api" }

Write-Host "[3/4] Building pricing-prometheus..." -ForegroundColor Yellow
podman build -f Dockerfile.prometheus -t localhost/pricing-prometheus .
if ($LASTEXITCODE -ne 0) { throw "Failed to build pricing-prometheus" }

Write-Host "[4/4] Building pricing-grafana..." -ForegroundColor Yellow
podman build -f Dockerfile.grafana -t localhost/pricing-grafana .
if ($LASTEXITCODE -ne 0) { throw "Failed to build pricing-grafana" }

Write-Host ""
Write-Host "=== All images built successfully ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  podman-compose up        # start the full stack"
Write-Host "  podman-compose down      # stop and remove containers"
Write-Host ""
Write-Host "Services will be available at:" -ForegroundColor Cyan
Write-Host "  API + Dashboard: http://localhost:8000 (dashboard at /dashboard)"
Write-Host "  Prometheus:      http://localhost:9090"
Write-Host "  Grafana:         http://localhost:3000 (admin/admin)"
