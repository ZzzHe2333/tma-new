param([string]$PackagePath='', [string]$ConfigPath='', [switch]$InitializeCertificate, [switch]$CheckOnly,
      [ValidateSet('ZzzHe','ZzzHe Local Test')][string]$PublisherName)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_windows_signing.ps1')
if (-not $ConfigPath) { $ConfigPath = Get-TmaLocalSigningConfigPath }
if ($InitializeCertificate) {
    $initialize = @{ConfigPath=$ConfigPath}
    if ($PublisherName) { $initialize.PublisherName=$PublisherName }
    Initialize-TmaLocalSigningCertificate @initialize | Out-Null
}
if (-not $PackagePath) {
    if (-not $InitializeCertificate) { throw 'Specify -PackagePath or -InitializeCertificate.' }
    Write-Output "Local signing configuration: $ConfigPath"
    return
}
Invoke-TmaLocalReleaseSigning -PackagePath $PackagePath -ConfigPath $ConfigPath -CheckOnly:$CheckOnly | ConvertTo-Json -Depth 4
