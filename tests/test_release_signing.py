"""Windows release configuration and fail-closed signing, without a private key."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PS = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(sys.platform != "win32" or not PS, reason="Windows signing tools")


def windows_ps_env():
    # The test runner may inherit PowerShell 7 module paths. Windows PowerShell
    # 5.1 must load its own built-in modules, not incompatible v7 type data.
    env = os.environ.copy()
    env["PSModulePath"] = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/Modules")
    return env


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(code, ok=True):
    result = subprocess.run(
        [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
         "$ErrorActionPreference='Stop'; . " + quote(ROOT / "tools/windows_signing.ps1") + "; " + code],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=windows_ps_env(),
    )
    if ok:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout
        assert "UnauthorizedAccess" not in result.stderr, result.stderr
    return result


@pytest.fixture
def config(tmp_path):
    target = tmp_path / "release-signing.json"
    shutil.copyfile(ROOT / "config/release-signing.example.json", target)
    return target


def test_initialize_preserves_existing_config(tmp_path):
    path = tmp_path / "nested/config.json"
    run_ps("Initialize-TmaSigningConfig " + quote(path))
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    assert data["enabled"] is False and data["certificate_thumbprint"] == ""
    path.write_text("preserve existing file", encoding="utf-8")
    run_ps("Initialize-TmaSigningConfig " + quote(path))
    assert path.read_text() == "preserve existing file"


@pytest.mark.parametrize("changes", [
    {"version": "1"}, {"version": True}, {"enabled": "true"},
    {"password": "do not store secrets"}, {"certificate_thumbprint": "bad"},
    {"store_location": "Root"}, {"timestamp_url": "https://user:password@example.com"},
    {"timestamp_url": "file:///timestamp"}, {"timestamp_url": "https://example.com/#fragment"},
])
def test_reject_invalid_config(config, changes):
    data = json.loads(config.read_text())
    data.update(changes)
    config.write_text(json.dumps(data))
    run_ps("Read-TmaSigningConfig " + quote(config), ok=False)


def test_signing_arguments_preserve_paths(config):
    output = run_ps(
        "$c=Read-TmaSigningConfig " + quote(config) + "; "
        "$c.store_location='LocalMachine'; $c.certificate_thumbprint=('A'*40); "
        "@(Get-TmaSigningArguments $c 'C:\\release folder\\example.exe') | ConvertTo-Json"
    )
    args = json.loads(output.stdout)
    assert args[-1] == r"C:\release folder\example.exe"
    assert args[args.index("/fd") + 1] == "SHA256"
    assert args[args.index("/td") + 1] == "SHA256"
    assert args[args.index("/tr") + 1] == "http://timestamp.digicert.com"
    assert "/sm" in args and args[args.index("/sha1") + 1] == "A" * 40


def test_require_signature_fails_before_build(config, tmp_path):
    target = tmp_path / "must-not-build"
    result = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "tools/build_windows.ps1"),
                             "-SigningConfig", str(config), "-DistPath", str(target), "-RequireSignature"],
                            capture_output=True, timeout=30, env=windows_ps_env())
    assert result.returncode != 0
    assert b"signing is disabled" in result.stderr
    assert not target.exists()


def test_enabled_without_certificate_fails(config):
    data = json.loads(config.read_text())
    data["enabled"] = True
    config.write_text(json.dumps(data))
    run_ps("Get-TmaSigningPlan (Read-TmaSigningConfig " + quote(config) + ")", ok=False)


@pytest.fixture
def package(tmp_path):
    # Real PE fixture supplied by Windows; no test certificate is installed.
    folder = tmp_path / "release with spaces"
    folder.mkdir()
    shutil.copyfile(PS, folder / "ZzzHe TMA Analysis.exe")
    return folder


def test_check_only_no_writes_and_disabled_report_honest(config, package):
    exe = package / "ZzzHe TMA Analysis.exe"
    original = hashlib.sha256(exe.read_bytes()).hexdigest()
    call = "Invoke-TmaReleaseSigning -PackagePath " + quote(package) + " -ConfigPath " + quote(config)
    run_ps(call + " -CheckOnly | Out-Null")
    assert sorted(p.name for p in package.iterdir()) == [exe.name]
    run_ps(call + " | Out-Null")
    report = json.loads((package / "release-security.json").read_text(encoding="utf-8-sig"))
    assert report["signing_enabled"] is False
    assert report["sha256"] == original
    assert hashlib.sha256(exe.read_bytes()).hexdigest() == original
    assert (package / "SHA256SUMS.txt").read_text().strip() == original + "  *" + exe.name
    assert report["signature_status"] in {"Valid", "NotSigned", "UnknownError"}


@pytest.mark.parametrize("mode", ["tool_failure", "verification_rejected", "missing_timestamp", "wrong_publisher"])
def test_failure_leaves_original_and_removes_only_temporary_copy(config, package, mode):
    original = (package / "ZzzHe TMA Analysis.exe").read_bytes()
    sentinel = package / "keep.txt"
    sentinel.write_text("keep")
    # Override only in this child process. No real signing or certificate changes.
    mock = "function Get-TmaSigningPlan { [pscustomobject]@{Enabled=$true;Tool='mock';Certificate=$null} }; "
    if mode == "tool_failure":
        mock += "function Invoke-TmaSignTool { throw 'simulated signing failure' }; "
    elif mode == "verification_rejected":
        mock += "function Invoke-TmaSignTool {}; function Get-AuthenticodeSignature { [pscustomobject]@{Status='NotSigned';SignerCertificate=$null;TimeStamperCertificate=$null} }; "
    else:
        stamp = "$null" if mode == "missing_timestamp" else "[pscustomobject]@{Subject='mock timestamp'}"
        mock += "function Invoke-TmaSignTool {}; function Get-AuthenticodeSignature { [pscustomobject]@{Status='Valid';SignerCertificate=[pscustomobject]@{Thumbprint=('B'*40)};TimeStamperCertificate=" + stamp + "} }; "
    run_ps(mock + "Invoke-TmaReleaseSigning -PackagePath " + quote(package) + " -ConfigPath " + quote(config), ok=False)
    assert (package / "ZzzHe TMA Analysis.exe").read_bytes() == original
    assert sentinel.read_text() == "keep"
    assert not list(package.glob(".signing-*"))
    assert not (package / "release-security.json").exists()


def run_local_ps(code, ok=True):
    return run_ps(". " + quote(ROOT / "tools/local_windows_signing.ps1") + "; " + code, ok=ok)


def test_author_config_preferred_without_replacing_legacy(tmp_path):
    legacy = tmp_path/'ZzzHeTMA/local-signing.json'
    author = legacy.with_name('local-author-signing.json')
    legacy.parent.mkdir();legacy.write_text('legacy')
    prefix = '$env:LOCALAPPDATA=' + quote(tmp_path) + '; '
    result=run_local_ps(prefix+'Get-TmaLocalSigningConfigPath')
    assert Path(result.stdout.strip())==legacy
    author.write_text('author')
    result=run_local_ps(prefix+'Get-TmaLocalSigningConfigPath')
    assert Path(result.stdout.strip())==author and legacy.read_text()=='legacy'


@pytest.mark.parametrize('subject', ['CN=ZzzHe','CN=ZzzHe Local Test','CN=Unexpected'])
def test_local_pinned_author_subjects(config, subject):
    data=json.loads(config.read_text());data.update(enabled=True,certificate_thumbprint='A'*40)
    config.write_text(json.dumps(data))
    mock=("$oids=New-Object Security.Cryptography.OidCollection; "
          "$oids.Add((New-Object Security.Cryptography.Oid '1.3.6.1.5.5.7.3.3')) | Out-Null; "
          "$eku=New-Object Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension($oids,$false); "
          "$script:fake=[pscustomobject]@{Subject="+quote(subject)+";Issuer="+quote(subject)+";HasPrivateKey=$true;NotBefore=(Get-Date).AddDays(-1);NotAfter=(Get-Date).AddDays(1);Extensions=@($eku)}; "
          "function Get-Item {param($LiteralPath) $script:fake}; ")
    result=run_local_ps(mock+'(Get-TmaLocalSigningCertificate (Read-TmaSigningConfig '+quote(config)+')).Subject',ok=subject!='CN=Unexpected')
    if subject!='CN=Unexpected':assert result.stdout.strip()==subject


def test_new_author_certificate_is_nonexportable_user_my_only(tmp_path):
    config=tmp_path/'author.json'
    mock=("function Find-TmaSignTool {'mock-signtool'}; "
          "function New-SelfSignedCertificate { param($Type,$Subject,$FriendlyName,$CertStoreLocation,$KeyAlgorithm,$KeyLength,$HashAlgorithm,$KeyExportPolicy,$NotAfter); "
          "$script:observed=[pscustomobject]@{subject=$Subject;store=$CertStoreLocation;policy=$KeyExportPolicy;algorithm=$KeyAlgorithm;bits=$KeyLength;hash=$HashAlgorithm}; "
          "[pscustomobject]@{Thumbprint=('A'*40)} }; ")
    result=run_local_ps(mock+'Initialize-TmaLocalSigningCertificate '+quote(config)+' -PublisherName ZzzHe | Out-Null; $script:observed | ConvertTo-Json')
    observed=json.loads(result.stdout)
    assert observed=={'subject':'CN=ZzzHe','store':'Cert:\\CurrentUser\\My','policy':'NonExportable','algorithm':'RSA','bits':3072,'hash':'SHA256'}
    assert json.loads(config.read_text(encoding='utf-8-sig'))['certificate_thumbprint']=='A'*40


def test_existing_different_publisher_is_not_silently_replaced(config):
    original=config.read_bytes()
    mock="function Get-TmaLocalSigningCertificate { [pscustomobject]@{Subject='CN=ZzzHe Local Test'} }; "
    result=run_local_ps(mock+'Initialize-TmaLocalSigningCertificate '+quote(config)+' -PublisherName ZzzHe',ok=False)
    assert 'separate configuration path' in result.stderr and config.read_bytes()==original


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"enabled": True, "store_location": "LocalMachine"},
    {"enabled": True, "certificate_thumbprint": ""},
])
def test_local_requires_its_enabled_user_certificate(config, changes):
    data = json.loads(config.read_text())
    data.update(changes)
    config.write_text(json.dumps(data))
    result = run_local_ps("Get-TmaLocalSigningPlan " + quote(config), ok=False)
    assert "Local test signing requires" in result.stderr


def test_local_cannot_satisfy_public_release_requirement(tmp_path):
    target = tmp_path / "must-not-build"
    result = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "tools/build_windows.ps1"),
                             "-DistPath", str(target), "-LocalTestSigning", "-RequireSignature"],
                            capture_output=True, timeout=30, env=windows_ps_env())
    assert result.returncode != 0
    assert b"cannot satisfy the public release" in result.stderr
    assert not target.exists()


@pytest.mark.parametrize("mode", ["tool_failure", "signature_failure"])
def test_local_failure_keeps_original(config, package, mode):
    exe = package / "ZzzHe TMA Analysis.exe"
    original = exe.read_bytes()
    mock = "function Get-TmaLocalSigningPlan { [pscustomobject]@{Config=(Read-TmaSigningConfig " + quote(config) + ");Certificate=[pscustomobject]@{Thumbprint=('A'*40)};Tool='mock'} }; "
    if mode == "tool_failure":
        mock += "function Invoke-TmaSignTool { throw 'simulated signing failure' }; "
    else:
        mock += "function Invoke-TmaSignTool {}; function Test-TmaLocalFileSignature { throw 'simulated verification failure' }; "
    result = run_local_ps(mock + "Invoke-TmaLocalReleaseSigning -PackagePath " + quote(package), ok=False)
    assert "simulated" in result.stderr
    assert exe.read_bytes() == original
    assert not list(package.glob(".signing-*"))
    assert not (package / "release-security.json").exists()


@pytest.mark.parametrize("mode", ["wrong_publisher", "unsigned", "missing_timestamp"])
def test_local_rejects_unpinned_signer_or_missing_timestamp(mode):
    if mode == "unsigned":
        signer = "$null"
    else:
        signer = "[pscustomobject]@{Thumbprint=('A'*40)}"
    expected = "B" * 40 if mode == "wrong_publisher" else "A" * 40
    mock = "function Get-AuthenticodeSignature { [pscustomobject]@{SignerCertificate=" + signer + ";TimeStamperCertificate=$null} }; "
    result = run_local_ps(mock + "Test-TmaLocalFileSignature 'unused.exe' '" + expected + "'", ok=False)
    assert "does not match" in result.stderr or "timestamp is missing" in result.stderr
