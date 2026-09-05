param(
    [string]$ProjectUrl = "https://mecytxaqgpcbkxrnfhee.supabase.co",
    [string]$SecretKey = $env:SUPABASE_SECRET_KEY
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SecretKey)) {
    $secureKey = Read-Host "Enter the Supabase secret key (input is hidden)" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try {
        $SecretKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

if ($SecretKey -notlike "sb_secret_*") {
    throw "Use the Supabase sb_secret_ key for backups. Never put this key in the website or Netlify."
}

$headers = @{
    apikey = $SecretKey
    Authorization = "Bearer $SecretKey"
}

$pageSize = 1000
$offset = 0
$allRows = [System.Collections.Generic.List[object]]::new()

do {
    $uri = "$($ProjectUrl.TrimEnd('/'))/rest/v1/labeling_decisions?select=*&order=submitted_at.asc&limit=$pageSize&offset=$offset"
    $page = @(Invoke-RestMethod -Method Get -Uri $uri -Headers $headers)
    foreach ($row in $page) {
        $allRows.Add($row)
    }
    $offset += $page.Count
} while ($page.Count -eq $pageSize)

$backupDirectory = Join-Path $PSScriptRoot "..\backups"
New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$timestampedPath = Join-Path $backupDirectory "labeling_decisions_$stamp.csv"
$latestPath = Join-Path $backupDirectory "labeling_decisions_latest.csv"

if ($allRows.Count -eq 0) {
    "No decisions have been submitted yet." | Set-Content -Path $timestampedPath -Encoding utf8
    Copy-Item -LiteralPath $timestampedPath -Destination $latestPath -Force
}
else {
    $allRows | Export-Csv -Path $timestampedPath -NoTypeInformation -Encoding utf8
    $allRows | Export-Csv -Path $latestPath -NoTypeInformation -Encoding utf8
}

Write-Output "Backed up $($allRows.Count) decisions."
Write-Output "Snapshot: $timestampedPath"
Write-Output "Latest:   $latestPath"
