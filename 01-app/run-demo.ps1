param([switch]$Install,[switch]$Clean,[switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendPath = Join-Path $projectRoot 'backend'
$frontendPath = Join-Path $projectRoot 'frontend'
$runPath = Join-Path $projectRoot '.run'
$pidFile = Join-Path $runPath 'processes.json'
$dependencyMarker = Join-Path $runPath 'dependency-state.txt'
New-Item -ItemType Directory -Force -Path $runPath | Out-Null

function Test-Endpoint([string]$Url) {
  # The first Next.js request can compile a route and take longer than two seconds.
  try { return (Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 8).StatusCode -eq 200 } catch { return $false }
}
function Get-ListenerProcess([int]$Port) {
  $match = netstat.exe -ano -p tcp | Select-String -Pattern "^\s*TCP\s+127\.0\.0\.1:$Port\s+.*LISTENING\s+(\d+)\s*$" | Select-Object -First 1
  if ($match) { return [int]$match.Matches[0].Groups[1].Value }
  return $null
}
function Open-Workspace {
  if (-not $NoBrowser) {
    try { Start-Process 'http://localhost:3000/login' } catch { Write-Warning 'Could not open the browser automatically.' }
  }
  Write-Host 'SIF Sentinel is running at http://localhost:3000/login'
  Write-Host "Logs: $runPath"
}

$backendReady = Test-Endpoint 'http://127.0.0.1:8000/health'
$frontendReady = Test-Endpoint 'http://127.0.0.1:3000/login'
if ($backendReady -and $frontendReady -and -not $Clean) {
  if (-not (Test-Path $dependencyMarker)) {
    $runningFiles = @((Join-Path $backendPath 'requirements.txt'),(Join-Path $frontendPath 'package.json'),(Join-Path $frontendPath 'package-lock.json')) | Where-Object { Test-Path $_ }
    (($runningFiles | ForEach-Object { (Get-FileHash -Algorithm SHA256 $_).Hash }) -join ':') | Set-Content -LiteralPath $dependencyMarker
  }
  Open-Workspace
  exit 0
}

if (Test-Path $pidFile) {
  & (Join-Path $projectRoot 'stop-demo.ps1') -Quiet
  Start-Sleep -Seconds 1
}
$frontendOwner = Get-ListenerProcess 3000
$backendOwner = Get-ListenerProcess 8000
if ($frontendOwner -or $backendOwner) {
  throw "Cannot start safely because another process owns port 3000 or 8000 (frontend PID: $frontendOwner; backend PID: $backendOwner). Close that process or restart Windows, then run this launcher again."
}

function Get-DependencyState {
  $files = @(
    (Join-Path $backendPath 'requirements.txt'),
    (Join-Path $frontendPath 'package.json'),
    (Join-Path $frontendPath 'package-lock.json')
  ) | Where-Object { Test-Path $_ }
  return (($files | ForEach-Object { (Get-FileHash -Algorithm SHA256 $_).Hash }) -join ':')
}

$dependencyState = Get-DependencyState
$needsInstall = $Install -or -not (Test-Path (Join-Path $backendPath '.venv\Scripts\python.exe')) -or -not (Test-Path (Join-Path $frontendPath 'node_modules')) -or -not (Test-Path $dependencyMarker) -or ((Get-Content -Raw $dependencyMarker).Trim() -ne $dependencyState)
if ($needsInstall) {
  if (-not (Test-Path (Join-Path $backendPath '.venv\Scripts\python.exe'))) {
    python -m venv (Join-Path $backendPath '.venv')
  }
  & (Join-Path $backendPath '.venv\Scripts\python.exe') -m pip install -r (Join-Path $backendPath 'requirements.txt')
  Push-Location $frontendPath
  try { npm install } finally { Pop-Location }
  Set-Content -LiteralPath $dependencyMarker -Value $dependencyState
}

$nextCache = Join-Path $frontendPath '.next'
if ($Clean -and (Test-Path $nextCache)) {
  $resolvedCache = (Resolve-Path $nextCache).Path
  if (-not $resolvedCache.StartsWith($frontendPath)) { throw 'Refusing to clear a cache outside the frontend directory.' }
  Remove-Item -LiteralPath $resolvedCache -Recurse -Force
}
$backendLog = Join-Path $runPath 'backend.log'
$backendErrorLog = Join-Path $runPath 'backend-error.log'
$frontendLog = Join-Path $runPath 'frontend.log'
$frontendErrorLog = Join-Path $runPath 'frontend-error.log'
foreach ($logFile in @($backendLog,$backendErrorLog,$frontendLog,$frontendErrorLog)) {
  Remove-Item -LiteralPath $logFile -Force -ErrorAction SilentlyContinue
}

# This launcher is intentionally loopback-only. Production deployments must
# provide SIF_AUTH_TOKENS instead of enabling this explicit demo mode.
$env:SIF_LOCAL_DEMO = '1'
$backendProc = Start-Process -FilePath (Join-Path $backendPath '.venv\Scripts\python.exe') -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $backendPath -WindowStyle Hidden -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog -PassThru
$nodeExe = (Get-Command 'node.exe').Source
Push-Location $frontendPath
try {
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed (exit code $LASTEXITCODE)." }
} finally { Pop-Location }
$frontendProc = Start-Process -FilePath $nodeExe -ArgumentList '.\node_modules\next\dist\bin\next','start','--hostname','127.0.0.1','--port','3000' -WorkingDirectory $frontendPath -WindowStyle Hidden -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog -PassThru
@{ backend = $backendProc.Id; frontend = $frontendProc.Id } | ConvertTo-Json | Set-Content $pidFile

$backendReady = $false
$frontendReady = $false
for ($attempt = 0; $attempt -lt 45; $attempt++) {
  $backendReady = Test-Endpoint 'http://127.0.0.1:8000/health'
  $frontendReady = Test-Endpoint 'http://127.0.0.1:3000/login'
  if ($backendReady -and $frontendReady) { break }
  if ($backendProc.HasExited -or $frontendProc.HasExited) { break }
  Start-Sleep -Seconds 1
}
if (-not $backendReady -or -not $frontendReady) {
  & (Join-Path $projectRoot 'stop-demo.ps1') -Quiet
  throw "SIF Sentinel did not start. Read backend-error.log and frontend-error.log in $runPath"
}
Open-Workspace
