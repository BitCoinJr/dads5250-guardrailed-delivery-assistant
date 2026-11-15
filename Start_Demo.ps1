param([int]$Port = 8501, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose a port between 1024 and 65535.' }
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & (Join-Path $PSScriptRoot 'Setup.ps1')
}
& $venvPython -c 'import streamlit, langgraph, openai, duckdb, dbt, google.auth, google_auth_oauthlib'
if ($LASTEXITCODE -ne 0) { throw 'Required libraries are missing. Run Setup.ps1.' }
& $venvPython -m streamlit run (Join-Path $PSScriptRoot 'app.py') --server.address=127.0.0.1 --server.port=$Port --server.headless=$($NoBrowser.IsPresent.ToString().ToLowerInvariant())
