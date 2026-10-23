param([string]$DistPath = 'dist',[string]$SigningConfig = '',[switch]$RequireSignature,[switch]$LocalTestSigning)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'windows_signing.ps1')
if ($LocalTestSigning) {
    if ($RequireSignature) { throw 'LocalTestSigning cannot satisfy the public release RequireSignature policy.' }
    . (Join-Path $PSScriptRoot 'local_windows_signing.ps1')
    if (-not $SigningConfig) { $SigningConfig = Get-TmaLocalSigningConfigPath }
    Get-TmaLocalSigningPlan $SigningConfig | Out-Null
} else {
    if (-not $SigningConfig) { $SigningConfig = Get-TmaSigningConfigPath }
    Initialize-TmaSigningConfig $SigningConfig | Out-Null
    Get-TmaSigningPlan (Read-TmaSigningConfig $SigningConfig) -RequireSignature:$RequireSignature | Out-Null
}
$distributionPath = if ([IO.Path]::IsPathRooted($DistPath)) { $DistPath } else { Join-Path $projectPath $DistPath }
$packagePath = Join-Path $distributionPath 'ZzzHe TMA Analysis'
$pythonExecutable = (Get-Command python.exe).Source
$buildOriginalPath = $env:PATH
$pythonDirectory = Split-Path -Parent $pythonExecutable
# Dependency discovery must not pick unrelated ICU/API DLLs from tools such as
# Poppler on the calling shell PATH. This affects this build process only.
$env:PATH = @($pythonDirectory, (Join-Path $pythonDirectory 'Scripts'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
Push-Location -LiteralPath $projectPath
try {
    & $pythonExecutable -m PyInstaller --noconfirm --clean --distpath $distributionPath 'ZzzHe TMA Analysis.spec'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    Copy-Item -LiteralPath (Join-Path $projectPath 'README.md') -Destination (Join-Path $packagePath 'README.md')
    Copy-Item -LiteralPath (Join-Path $projectPath 'tools\diagnostic_start.cmd') -Destination (Join-Path $packagePath 'diagnostic_start.cmd')
    Copy-Item -LiteralPath (Join-Path $projectPath 'docs\windows-release-signing.md') -Destination (Join-Path $packagePath 'WINDOWS_SIGNING.md')
    $docsDestination = Join-Path $packagePath 'docs'
    New-Item -ItemType Directory -Force -Path $docsDestination | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectPath 'docs\windows-release-signing.md') -Destination $docsDestination
    $powerDestination = Join-Path $packagePath 'power'
    New-Item -ItemType Directory -Force -Path $powerDestination | Out-Null
    foreach ($sourceName in @('piliang_tma_v14.py', 'one_BG_neibuban.py', 'one_BG_claude_v6.py')) {
        Copy-Item -LiteralPath (Join-Path $projectPath "power\$sourceName") -Destination $powerDestination
    }
    & $pythonExecutable -c 'import sys; from tools.build_t1_t2_h_standalone import build; build(sys.argv[1])' (Join-Path $packagePath 'T1-T2-H\extract_t1_t2_h.py')
    if ($LASTEXITCODE -ne 0) { throw 'Standalone T1/T2/H script build failed' }
    # Signing is the final binary mutation. Hashes are generated afterwards.
    if ($LocalTestSigning) {
        Invoke-TmaLocalReleaseSigning -PackagePath $packagePath -ConfigPath $SigningConfig | ConvertTo-Json -Depth 4
    } else {
        Invoke-TmaReleaseSigning -PackagePath $packagePath -ConfigPath $SigningConfig -RequireSignature:$RequireSignature | ConvertTo-Json -Depth 4
    }
} finally {
    $env:PATH = $buildOriginalPath
    Pop-Location
}
