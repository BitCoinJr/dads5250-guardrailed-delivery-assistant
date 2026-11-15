param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$uvTool = Get-Command uv -ErrorAction SilentlyContinue
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($uvTool) {
        if ($PythonPath) {
            & $uvTool.Source venv --python $PythonPath '.venv'
        } else {
            & $uvTool.Source venv --python '3.12' --managed-python '.venv'
        }
    } elseif ($PythonPath) {
        & $PythonPath -m venv '.venv'
    } else {
        & py -3.12 -m venv '.venv'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed. Install Python 3.12 or uv and retry.' }
}
if ($uvTool) {
    & $uvTool.Source pip sync --python $venvPython 'requirements.lock.txt'
} else {
    & $venvPython -m pip install -r 'requirements.lock.txt'
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Setup complete. Run Start_Demo.ps1 or Run_Demo.cmd.'
