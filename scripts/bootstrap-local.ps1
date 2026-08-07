# Bootstrap the Dynamic Pricing MAB system locally (no containers).
#
# This generates synthetic historical data and trains all models.
# After running this, you'll have:
#   - data/pricing.db (SQLite database with properties + historical decisions)
#   - model_registry/artifacts/ (trained VW model files)
#
# Usage:
#   cd c:\hackathon\dynamic-pricing-MAB
#   .\.venv\Scripts\Activate.ps1
#   .\scripts\bootstrap-local.ps1
#
# Then start the API (serves both the API and the frontend dashboard):
#   uvicorn serving.api:app --host 0.0.0.0 --port 8000
#   Open http://localhost:8000/dashboard

$ErrorActionPreference = "Stop"

Write-Host "=== Dynamic Pricing MAB - Local Bootstrap ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "This will generate synthetic data and train all models." -ForegroundColor Yellow
Write-Host "Expected runtime: 2-5 minutes depending on hardware." -ForegroundColor Yellow
Write-Host ""

# Run the bootstrap pipeline
python -m orchestration.pipelines.run_bootstrap

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=== Bootstrap complete ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Created:" -ForegroundColor Cyan
    Write-Host "  - data/pricing.db (SQLite database)"
    Write-Host "  - model_registry/artifacts/ (trained models)"
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Start the API:       uvicorn serving.api:app --host 0.0.0.0 --port 8000"
    Write-Host "  2. Open dashboard:      http://localhost:8000/dashboard"
} else {
    Write-Host ""
    Write-Host "=== Bootstrap FAILED ===" -ForegroundColor Red
    Write-Host "Check the error output above."
    exit 1
}
