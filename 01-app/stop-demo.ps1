param([switch]$Quiet)
$ErrorActionPreference = 'SilentlyContinue'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $projectRoot '.run\processes.json'
if (Test-Path $pidFile) {
  $processes = Get-Content -Raw $pidFile | ConvertFrom-Json
  $processIds = @($processes.backend, $processes.frontend)
  foreach ($processId in ($processIds | Where-Object { $_ } | Select-Object -Unique)) {
    & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
  }
  Remove-Item -LiteralPath $pidFile -Force
  if (-not $Quiet) { Write-Host 'SIF Sentinel stopped.' }
} elseif (-not $Quiet) { Write-Host 'No SIF Sentinel processes were recorded.' }
