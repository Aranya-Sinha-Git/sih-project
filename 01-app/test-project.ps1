$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendPath = Join-Path $projectRoot 'backend'
$frontendPath = Join-Path $projectRoot 'frontend'
& (Join-Path $projectRoot 'stop-demo.ps1') -Quiet
Push-Location $frontendPath
try {
  Push-Location $backendPath
  try {
    & '.\.venv\Scripts\python.exe' -m pytest -q tests/test_api.py
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed (exit code $LASTEXITCODE)." }
  } finally { Pop-Location }
  & (Join-Path $projectRoot 'backend\.venv\Scripts\python.exe') -m pytest -q (Join-Path $projectRoot '..\03-training\ml\sif_v0_1\tests\test_pipeline.py') -k 'human_evaluator or calibration'
  if ($LASTEXITCODE -ne 0) { throw "Evaluator checks failed (exit code $LASTEXITCODE)." }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "Frontend build failed (exit code $LASTEXITCODE)." }
} finally { Pop-Location }
Write-Host 'Backend tests and frontend production build passed.'
