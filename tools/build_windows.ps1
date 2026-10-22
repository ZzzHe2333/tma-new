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
    & $pythonExecutable -m PyInstaller --noconfirm --clean 'ZzzHe TMA Analysis.spec'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    Copy-Item -LiteralPath (Join-Path $projectPath 'README.md') -Destination (Join-Path $projectPath 'dist\ZzzHe TMA Analysis\README.md')
} finally {
    $env:PATH = $buildOriginalPath
    Pop-Location
}
