$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonExecutable = (Get-Command python.exe).Source
$buildOriginalPath = $env:PATH
$pythonDirectory = Split-Path -Parent $pythonExecutable
# Dependency discovery must not pick unrelated ICU/API DLLs from tools such as
# Poppler on the calling shell PATH. This affects this build process only.
$env:PATH = @($pythonDirectory, (Join-Path $pythonDirectory 'Scripts'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
Push-Location -LiteralPath $projectPath
try {
    & $pythonExecutable -m PyInstaller --noconfirm --clean --onedir --windowed --name TMA-Studio --add-data 'tma_app\assets;tma_app\assets' --exclude-module tkinter --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module torch --exclude-module pandas --exclude-module IPython --exclude-module notebook --exclude-module jupyterlab run.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    Copy-Item -LiteralPath (Join-Path $projectPath 'README.md') -Destination (Join-Path $projectPath 'dist\TMA-Studio\README.md')
} finally {
    $env:PATH = $buildOriginalPath
    Pop-Location
}
