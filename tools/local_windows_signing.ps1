# Local test signatures only. No Root/TrustedPublisher store modifications.
. (Join-Path $PSScriptRoot 'windows_signing.ps1')

function Get-TmaLocalSigningConfigPath {
    $folder = Split-Path -Parent (Get-TmaSigningConfigPath)
    $author = Join-Path $folder 'local-author-signing.json'
    if (Test-Path -LiteralPath $author -PathType Leaf) { return $author }
    return Join-Path $folder 'local-signing.json'
}

function Get-TmaLocalSigningCertificate {
    param($Config)
    if (-not $Config.enabled -or $Config.store_location -ne 'CurrentUser' -or -not $Config.certificate_thumbprint) {
        throw 'Local test signing requires its own enabled CurrentUser/My certificate configuration.'
    }
    $cert = Get-Item -LiteralPath ('Cert:\CurrentUser\My\' + $Config.certificate_thumbprint) -ErrorAction Stop
    $now = Get-Date
    if ($cert.Subject -notin @('CN=ZzzHe Local Test','CN=ZzzHe') -or $cert.Subject -ne $cert.Issuer -or -not $cert.HasPrivateKey -or $cert.NotBefore -gt $now -or $cert.NotAfter -le $now) {
        throw 'Expected a valid pinned ZzzHe self-signed code-signing certificate with its private key.'
    }
    $usage = @($cert.Extensions | Where-Object { $_ -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension] } | ForEach-Object { $_.EnhancedKeyUsages } | ForEach-Object { $_.Value })
    if ('1.3.6.1.5.5.7.3.3' -notin $usage) { throw 'Local certificate must have the Code Signing extended key usage.' }
    return $cert
}

function Initialize-TmaLocalSigningCertificate {
    param([string]$ConfigPath = (Get-TmaLocalSigningConfigPath),
          [ValidateSet('ZzzHe','ZzzHe Local Test')][string]$PublisherName = 'ZzzHe')
    if (Test-Path -LiteralPath $ConfigPath) {
        $existing = Get-TmaLocalSigningCertificate (Read-TmaSigningConfig $ConfigPath)
        if ($PSBoundParameters.ContainsKey('PublisherName') -and $existing.Subject -ne ('CN=' + $PublisherName)) {
            throw 'Existing signing identity differs. Use a separate configuration path; do not overwrite the old key or configuration.'
        }
        return $ConfigPath
    }
    $tool = Find-TmaSignTool
    if (-not $tool) { throw 'Windows SDK SignTool is required.' }
    # A non-exportable private key stays in the current user's key store.
    # The public .cer file later shipped in the package contains no private key.
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject ('CN=' + $PublisherName) `
        -FriendlyName 'ZzzHe TMA Analysis Self-Signed Publisher' -CertStoreLocation 'Cert:\CurrentUser\My' `
        -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy NonExportable `
        -NotAfter (Get-Date).AddYears(3) -ErrorAction Stop
    $config = [pscustomobject][ordered]@{
        version=1; enabled=$true; store_location='CurrentUser'; certificate_thumbprint=$cert.Thumbprint
        timestamp_url='http://timestamp.digicert.com'; signtool_path=$tool
    }
    $target = [IO.Path]::GetFullPath($ConfigPath)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $config | ConvertTo-Json | Set-Content -LiteralPath $target -Encoding UTF8
    return $target
}

function Get-TmaLocalSigningPlan {
    param([string]$ConfigPath = (Get-TmaLocalSigningConfigPath))
    $config = Read-TmaSigningConfig $ConfigPath
    $cert = Get-TmaLocalSigningCertificate $config
    $tool = Find-TmaSignTool $config.signtool_path
    if (-not $tool) { throw 'Windows SDK SignTool is required.' }
    return [pscustomobject]@{Config=$config; Certificate=$cert; Tool=$tool}
}

function Test-TmaLocalFileSignature {
    param([string]$ExecutablePath,[string]$ExpectedThumbprint)
    $signature = Get-AuthenticodeSignature -LiteralPath $ExecutablePath -ErrorAction Stop
    if (-not $ExpectedThumbprint -or -not $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -ne $ExpectedThumbprint) {
        throw 'Embedded signer does not match the configured local certificate.'
    }
    if (-not $signature.TimeStamperCertificate) { throw 'RFC3161 timestamp is missing.' }
    if (-not ('ZzzHe.Release.WinTrustProbe' -as [type])) {
        Add-Type -Path (Join-Path $PSScriptRoot 'WinTrustProbe.cs') -ErrorAction Stop
    }
    # This is NOT a successful Windows trust result. A pinned local test signature
    # is allowed to end at its untrusted self-signed root; other errors fail closed.
    $code = [ZzzHe.Release.WinTrustProbe]::Verify($ExecutablePath)
    $hex = '0x' + $code.ToString('X8')
    if ($hex -notin @('0x00000000','0x800B0109')) {
        throw "Local Authenticode file verification rejected: $hex"
    }
    return [pscustomobject]@{
        Signature=$signature; WinTrustCode=$hex
        WindowsTrusted=($hex -eq '0x00000000')
    }
}

function Invoke-TmaLocalReleaseSigning {
    param([string]$PackagePath,[string]$ConfigPath=(Get-TmaLocalSigningConfigPath),[switch]$CheckOnly)
    $plan = Get-TmaLocalSigningPlan $ConfigPath
    $package = (Get-Item -LiteralPath $PackagePath -ErrorAction Stop).FullName
    $executable = Join-Path $package 'ZzzHe TMA Analysis.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw 'ZzzHe TMA Analysis.exe not found.' }
    if (-not $CheckOnly) {
        $temporary = Join-Path $package ('.signing-' + [guid]::NewGuid().ToString('N') + '.exe')
        try {
            Copy-Item -LiteralPath $executable -Destination $temporary -ErrorAction Stop
            Invoke-TmaSignTool $plan.Tool (Get-TmaSigningArguments $plan.Config $temporary)
            Test-TmaLocalFileSignature $temporary $plan.Certificate.Thumbprint | Out-Null
            Move-Item -LiteralPath $temporary -Destination $executable -Force -ErrorAction Stop
        } finally {
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
        }
    }
    $verification = Test-TmaLocalFileSignature $executable $plan.Certificate.Thumbprint
    $publicFile = if ($plan.Certificate.Subject -eq 'CN=ZzzHe') { 'ZzzHe-Publisher.cer' } else { 'ZzzHe-Local-Test.cer' }
    $hash = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
    $report = [pscustomobject][ordered]@{
        status='local_test_signed_timestamped'; signing_mode='local_self_signed'; check_only=[bool]$CheckOnly
        signature_status=[string]$verification.Signature.Status
        winverifytrust_code=$verification.WinTrustCode; windows_trusted=$verification.WindowsTrusted
        public_ca_certificate=$false; root_certificate_installed_by_tool=$false
        publisher=$plan.Certificate.Subject; certificate_thumbprint=$plan.Certificate.Thumbprint
        public_certificate_file=$publicFile; certificate_embedded_in_exe=$true
        certificate_expires=$plan.Certificate.NotAfter.ToString('o')
        timestamp_present=$true; timestamp_publisher=$verification.Signature.TimeStamperCertificate.Subject
        signtool_path=$plan.Tool; executable='ZzzHe TMA Analysis.exe'; sha256=$hash
        smartscreen_reputation='Local self-signed test certificate. No SmartScreen reputation or public publisher trust is claimed.'
    }
    if (-not $CheckOnly) {
        Export-Certificate -Cert $plan.Certificate -FilePath (Join-Path $package $publicFile) -Type CERT -Force | Out-Null
        $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $package 'release-security.json') -Encoding UTF8
        "$hash  *ZzzHe TMA Analysis.exe" | Set-Content -LiteralPath (Join-Path $package 'SHA256SUMS.txt') -Encoding ASCII
        Write-Warning 'Local test signature only. Certificate was not installed as a trusted root; SmartScreen may still warn.'
    }
    return $report
}
