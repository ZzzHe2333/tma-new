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
    $powerDestination = Join-Path $projectPath 'dist\ZzzHe TMA Analysis\power'
    New-Item -ItemType Directory -Force -Path $powerDestination | Out-Null
    foreach ($sourceName in @('piliang_tma_v14.py', 'one_BG_neibuban.py', 'one_BG_claude_v6.py')) {
        Copy-Item -LiteralPath (Join-Path $projectPath "power\$sourceName") -Destination $powerDestination
    }
    & $pythonExecutable -c "from tools.build_t1_t2_h_standalone import build; build('dist/ZzzHe TMA Analysis/T1-T2-H/extract_t1_t2_h.py')"
    if ($LASTEXITCODE -ne 0) { throw 'Standalone T1/T2/H script build failed' }
} finally {
    $env:PATH = $buildOriginalPath
    Pop-Location
}
