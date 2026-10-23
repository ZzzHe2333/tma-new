param(
    [string]$PackagePath = '',
    [string]$ConfigPath = '',
    [switch]$InitializeConfig,
    [switch]$CheckOnly,
    [switch]$RequireSignature
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows_signing.ps1')
if (-not $ConfigPath) { $ConfigPath = Get-TmaSigningConfigPath }
if ($InitializeConfig) { Initialize-TmaSigningConfig $ConfigPath | Out-Null }
if (-not $PackagePath) {
    if (-not $InitializeConfig) { throw 'Specify -PackagePath or -InitializeConfig.' }
    Write-Output "Signing configuration: $ConfigPath"
    return
}
Invoke-TmaReleaseSigning -PackagePath $PackagePath -ConfigPath $ConfigPath -CheckOnly:$CheckOnly -RequireSignature:$RequireSignature | ConvertTo-Json -Depth 4
