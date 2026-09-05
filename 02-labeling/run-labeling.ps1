$ErrorActionPreference = 'Stop'
$labelingRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Split-Path -Parent $labelingRoot
$python = Join-Path $workspaceRoot '01-app\backend\.venv\Scripts\python.exe'
$app = Join-Path $workspaceRoot '03-training\ml\sif_v0_1\annotation_app.py'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend Python environment not found: $python"
}

Write-Host 'Starting the local SIF labeling interface...'
Write-Host 'Labels are stored permanently under 03-training\ml\sif_v0_1\data\local_label_store.'
& $python -m streamlit run $app --server.address 127.0.0.1 --server.port 8501
