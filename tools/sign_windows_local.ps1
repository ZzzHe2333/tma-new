param([string]$PackagePath='', [string]$ConfigPath='', [switch]$InitializeCertificate, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_windows_signing.ps1')
if (-not $ConfigPath) { $ConfigPath = Get-TmaLocalSigningConfigPath }
if ($InitializeCertificate) { Initialize-TmaLocalSigningCertificate $ConfigPath | Out-Null }
if (-not $PackagePath) {
    if (-not $InitializeCertificate) { throw 'Specify -PackagePath or -InitializeCertificate.' }
    Write-Output "Local signing configuration: $ConfigPath"
    return
}
Invoke-TmaLocalReleaseSigning -PackagePath $PackagePath -ConfigPath $ConfigPath -CheckOnly:$CheckOnly | ConvertTo-Json -Depth 4
