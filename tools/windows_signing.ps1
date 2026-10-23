# Functions only. No certificate or Windows security policy is installed/changed.
Set-StrictMode -Version 2

function Get-TmaSigningConfigPath {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is unavailable.' }
    return Join-Path $env:LOCALAPPDATA 'ZzzHeTMA\release-signing.json'
}

function Initialize-TmaSigningConfig {
    param([string]$ConfigPath = (Get-TmaSigningConfigPath))
    $target = [IO.Path]::GetFullPath($ConfigPath)
    if (-not (Test-Path -LiteralPath $target)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        $template = Join-Path (Split-Path -Parent $PSScriptRoot) 'config\release-signing.example.json'
        Copy-Item -LiteralPath $template -Destination $target -ErrorAction Stop
    }
    return $target
}

function Read-TmaSigningConfig {
    param([string]$ConfigPath = (Get-TmaSigningConfigPath))
    $data = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    $fields = @('version','enabled','store_location','certificate_thumbprint','timestamp_url','signtool_path')
    $actual = @($data.PSObject.Properties.Name)
    if ($actual.Count -ne $fields.Count -or @($actual | Where-Object { $_ -notin $fields }).Count) {
        throw 'Signing config must contain exactly the public template fields. Do not put passwords or private keys here.'
    }
    if (($data.version -isnot [int] -and $data.version -isnot [long]) -or $data.version -ne 1 -or $data.enabled -isnot [bool]) { throw 'Invalid signing configuration version/enabled value.' }
    foreach ($field in @('store_location','certificate_thumbprint','timestamp_url','signtool_path')) {
        if ($data.$field -isnot [string]) { throw "Signing field must be text: $field" }
    }
    if ($data.store_location -notin @('CurrentUser','LocalMachine')) { throw 'Certificate store must be CurrentUser or LocalMachine.' }
    $thumbprint = ($data.certificate_thumbprint -replace '\s','').ToUpperInvariant()
    if ($thumbprint -and $thumbprint -notmatch '^[0-9A-F]{40}$') { throw 'Use the 40-digit certificate thumbprint, not a password or file hash.' }
    $data.certificate_thumbprint = $thumbprint
    $uri = $null
    if (-not [Uri]::TryCreate($data.timestamp_url,[UriKind]::Absolute,[ref]$uri) -or $uri.Scheme -notin @('http','https') -or $uri.UserInfo -or $uri.Fragment) {
        throw 'An http(s) RFC3161 timestamp URL without embedded credentials is required.'
    }
    return $data
}

function Find-TmaSignTool {
    param([string]$ConfiguredPath = '')
    if ($ConfiguredPath) {
        $path = (Get-Item -LiteralPath $ConfiguredPath -ErrorAction Stop).FullName
        if ((Split-Path -Leaf $path) -ine 'signtool.exe') { throw 'signtool_path must point to Windows SDK signtool.exe.' }
        return $path
    }
    $command = Get-Command signtool.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    if (-not ${env:ProgramFiles(x86)}) { return $null }
    $sdk = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    if (Test-Path -LiteralPath $sdk) {
        $architecture = if ([Environment]::Is64BitProcess) { 'x64' } else { 'x86' }
        $versions = Get-ChildItem -LiteralPath $sdk -Directory | Where-Object { $_.Name -match '^\d+(\.\d+)+$' } | Sort-Object { [version]$_.Name } -Descending
        foreach ($version in $versions) {
            $tool = Join-Path $version.FullName "$architecture\signtool.exe"
            if (Test-Path -LiteralPath $tool -PathType Leaf) { return $tool }
        }
    }
    return $null
}

function Get-TmaSigningCertificate {
    param($Config)
    if (-not $Config.certificate_thumbprint) { throw 'No signing certificate configured. A publicly trusted code-signing identity is required.' }
    $path = 'Cert:\' + $Config.store_location + '\My\' + $Config.certificate_thumbprint
    $cert = Get-Item -LiteralPath $path -ErrorAction Stop
    $now = Get-Date
    if (-not $cert.HasPrivateKey -or $cert.NotBefore -gt $now -or $cert.NotAfter -le $now) {
        throw 'The signing certificate must have an accessible private key and be currently valid.'
    }
    $usage = @($cert.Extensions | Where-Object { $_ -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension] } | ForEach-Object { $_.EnhancedKeyUsages } | ForEach-Object { $_.Value })
    if ('1.3.6.1.5.5.7.3.3' -notin $usage) {
        throw 'The certificate does not have the Code Signing extended key usage.'
    }
    if ($cert.Subject -eq $cert.Issuer) { throw 'Self-signed certificates are not accepted for public releases.' }
    $chain = New-Object Security.Cryptography.X509Certificates.X509Chain
    try {
        $chain.ChainPolicy.UrlRetrievalTimeout = [TimeSpan]::FromSeconds(10)
        $chain.ChainPolicy.ApplicationPolicy.Add((New-Object Security.Cryptography.Oid '1.3.6.1.5.5.7.3.3'))
        if (-not $chain.Build($cert)) { throw 'The code-signing certificate chain could not be validated on this computer.' }
    } finally { $chain.Dispose() }
    return $cert
}

function Get-TmaSigningPlan {
    param($Config, [switch]$RequireSignature)
    if ($RequireSignature -and -not $Config.enabled) { throw 'Release requires a signature, but signing is disabled. Configure a trusted certificate first.' }
    $tool = Find-TmaSignTool $Config.signtool_path
    $cert = $null
    if ($Config.enabled) {
        if (-not $tool) { throw 'Install Windows SDK SignTool or set signtool_path.' }
        $cert = Get-TmaSigningCertificate $Config
    }
    return [pscustomobject]@{ Enabled=$Config.enabled; Tool=$tool; Certificate=$cert }
}

function Get-TmaSigningArguments {
    param($Config,[string]$ExecutablePath)
    $arguments = @('sign','/fd','SHA256','/tr',$Config.timestamp_url,'/td','SHA256','/s','My','/sha1',$Config.certificate_thumbprint,'/d','ZzzHe TMA Analysis')
    if ($Config.store_location -eq 'LocalMachine') { $arguments += '/sm' }
    return $arguments + $ExecutablePath
}

function Invoke-TmaSignTool {
    param([string]$Tool,[string[]]$Arguments)
    & $Tool @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "SignTool failed (exit $LASTEXITCODE). The release executable was not replaced." }
}

function Invoke-TmaReleaseSigning {
    param([string]$PackagePath,[string]$ConfigPath=(Get-TmaSigningConfigPath),[switch]$RequireSignature,[switch]$CheckOnly)
    $config = Read-TmaSigningConfig $ConfigPath
    $plan = Get-TmaSigningPlan $config -RequireSignature:$RequireSignature
    $package = (Get-Item -LiteralPath $PackagePath -ErrorAction Stop).FullName
    $executable = Join-Path $package 'ZzzHe TMA Analysis.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw 'ZzzHe TMA Analysis.exe not found in package directory.' }
    $signature = Get-AuthenticodeSignature -LiteralPath $executable -ErrorAction Stop
    if ($plan.Enabled -and -not $CheckOnly) {
        # Sign/verify a temporary copy; a timestamp or verification failure must
        # never replace the usable original with a partly signed executable.
        $temporary = Join-Path $package ('.signing-' + [guid]::NewGuid().ToString('N') + '.exe')
        try {
            Copy-Item -LiteralPath $executable -Destination $temporary -ErrorAction Stop
            Invoke-TmaSignTool $plan.Tool (Get-TmaSigningArguments $config $temporary)
            Invoke-TmaSignTool $plan.Tool @('verify','/pa','/all','/tw',$temporary)
            $signed = Get-AuthenticodeSignature -LiteralPath $temporary -ErrorAction Stop
            if ($signed.Status -ne 'Valid' -or -not $signed.SignerCertificate -or -not $signed.TimeStamperCertificate -or $signed.SignerCertificate.Thumbprint -ne $config.certificate_thumbprint) {
                throw 'Signature/publisher/timestamp validation failed; original executable is unchanged.'
            }
            Move-Item -LiteralPath $temporary -Destination $executable -Force -ErrorAction Stop
        } finally {
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $executable -ErrorAction Stop
    }
    $publisher = $null; $thumbprint = $null
    if ($signature.SignerCertificate) { $publisher=$signature.SignerCertificate.Subject; $thumbprint=$signature.SignerCertificate.Thumbprint }
    $hash = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
    $status = if ($signature.Status -eq 'Valid' -and $signature.TimeStamperCertificate) { 'signed_valid_timestamped' } elseif ($signature.Status -eq 'NotSigned') { 'unsigned' } else { 'signature_not_release_validated' }
    $report = [pscustomobject][ordered]@{
        status=$status; signing_enabled=$plan.Enabled; check_only=[bool]$CheckOnly
        signature_status=[string]$signature.Status; publisher=$publisher; certificate_thumbprint=$thumbprint
        timestamp_present=[bool]$signature.TimeStamperCertificate; signtool_path=$plan.Tool
        executable='ZzzHe TMA Analysis.exe'; sha256=$hash
        smartscreen_reputation='Not measured; code signing does not guarantee immediate SmartScreen reputation.'
    }
    if (-not $CheckOnly) {
        $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $package 'release-security.json') -Encoding UTF8
        "$hash  *ZzzHe TMA Analysis.exe" | Set-Content -LiteralPath (Join-Path $package 'SHA256SUMS.txt') -Encoding ASCII
        if ($status -eq 'unsigned') { Write-Warning 'Unsigned test build. SmartScreen may still show an unknown publisher warning.' }
    }
    return $report
}
