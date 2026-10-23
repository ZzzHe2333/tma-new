"""Verify the signed Windows package without changing certificate trust stores."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import pefile

ROOT = Path(__file__).resolve().parents[1]


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def powershell(code):
    env = os.environ.copy()
    env["PSModulePath"] = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/Modules")
    result = subprocess.run(
        [shutil.which("powershell.exe"), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
         "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); " + code],
        env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(package, output, inputs, trust_before=None):
    from tma_app import __version__
    output.mkdir(parents=True, exist_ok=True)
    executable = package / "ZzzHe TMA Analysis.exe"
    before = digest(executable)
    sources = {str(path): digest(path) for path in inputs}
    signature = powershell("& " + ps_quote(ROOT / "tools/sign_windows_local.ps1") +
                           " -PackagePath " + ps_quote(package) + " -CheckOnly")
    assert signature["sha256"] == before and signature["timestamp_present"]
    assert signature["signing_mode"] == "local_self_signed"
    checks = ["pinned_local_signature_rfc3161_timestamp_and_exe_hash"]

    with tempfile.TemporaryDirectory(prefix="signature-tamper-", dir=output) as private:
        tampered = Path(private) / "tampered.exe"
        data = bytearray(executable.read_bytes())
        with pefile.PE(data=data) as image:
            offset = next(s.PointerToRawData for s in image.sections if s.Name.rstrip(b"\0") == b".text") + 32
        data[offset] ^= 1
        tampered.write_bytes(data)
        probe = powershell(
            ". " + ps_quote(ROOT / "tools/local_windows_signing.ps1") + "; "
            "Test-TmaLocalFileSignature " + ps_quote(executable) + " '" + signature["certificate_thumbprint"] + "' | Out-Null; "
            "$code='0x'+[ZzzHe.Release.WinTrustProbe]::Verify(" + ps_quote(tampered) + ").ToString('X8'); "
            "$rejected=$false; try { Test-TmaLocalFileSignature " + ps_quote(tampered) + " '" + signature["certificate_thumbprint"] + "' | Out-Null } catch { $rejected=$true }; "
            "[pscustomobject]@{tampered_code=$code;tampered_rejected=$rejected} | ConvertTo-Json"
        )
        assert probe == {"tampered_code": "0x80096010", "tampered_rejected": True}, probe
    checks.append("changed_program_bytes_rejected_with_TRUST_E_BAD_DIGEST")

    certificate = powershell(
        ". " + ps_quote(ROOT / "tools/local_windows_signing.ps1") + "; $plan=Get-TmaLocalSigningPlan; "
        "$pub=New-Object Security.Cryptography.X509Certificates.X509Certificate2 " + ps_quote(package / "ZzzHe-Local-Test.cer") + "; "
        "$key=[Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($plan.Certificate); "
        "try { $policy=[string]$key.Key.ExportPolicy } finally { $key.Dispose() }; "
        "$formalRejected=$false; try { Get-TmaSigningCertificate $plan.Config | Out-Null } catch { if ($_.Exception.Message -match 'Self-signed') {$formalRejected=$true} else {throw} }; "
        "[pscustomobject]@{public_certificate_thumbprint=$pub.Thumbprint;public_file_has_private_key=$pub.HasPrivateKey;private_key_export_policy=$policy;formal_release_rejects_local_cert=$formalRejected} | ConvertTo-Json"
    )
    assert not certificate["public_file_has_private_key"]
    assert certificate["public_certificate_thumbprint"] == signature["certificate_thumbprint"]
    assert certificate["private_key_export_policy"] == "None"
    assert certificate["formal_release_rejects_local_cert"]
    checks.append("nonexportable_private_key_public_only_certificate_and_public_release_separation")

    reports = []
    for label, mode in (("batch", "--verify-batch"), ("mcp", "--verify-mcp"), ("normalization", "--verify-mass-normalization")):
        print("Checking frozen " + label, flush=True)
        target = output / ("frozen-" + label + ".json")
        env = os.environ.copy()
        env["LOCALAPPDATA"] = str(output / (label + "-profile"))
        env["QT_QPA_PLATFORM"] = "offscreen"
        with (output / (label + "-process.log")).open("wb") as log:
            result = subprocess.run([str(executable), mode, str(target), *map(str, inputs)],
                                    env=env, stdout=log, stderr=log, timeout=150)
        assert result.returncode == 0, (label, result.returncode)
        report = json.loads(target.read_text(encoding="utf-8-sig"))
        assert report["status"] == "passed", report
        assert report["version"] == __version__, report
        reports.append(str(target))
        checks.append("frozen_" + label)

    if trust_before:
        after = powershell(
            "@(foreach ($store in @('Cert:/CurrentUser/Root','Cert:/LocalMachine/Root','Cert:/CurrentUser/TrustedPublisher','Cert:/LocalMachine/TrustedPublisher')) "
            "{ [pscustomobject]@{store=$store;thumbprints=@(Get-ChildItem -LiteralPath $store | ForEach-Object Thumbprint | Sort-Object)} }) | ConvertTo-Json -Depth 4"
        )
        assert after == json.loads(trust_before.read_text(encoding="utf-8-sig"))
        (output / "trust-after.json").write_text(json.dumps(after, indent=2), encoding="utf-8")
        checks.append("root_and_trusted_publisher_stores_unchanged")
    assert digest(executable) == before
    assert sources == {str(path): digest(path) for path in inputs}
    checks.append("release_executable_and_real_sample_files_unchanged_by_qa")
    report = {"status": "passed", "version": __version__, "executable": str(executable),
              "exe_sha256": before, "checks": checks, "signature": signature, "certificate": certificate,
              "tamper_probe": probe, "reports": reports, "input_sha256": sources}
    (output / "release.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "version": __version__, "checks": checks}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trust-before", type=Path)
    parser.add_argument("inputs", type=Path, nargs=2)
    args = parser.parse_args()
    verify(args.package.resolve(), args.output.resolve(), [p.resolve() for p in args.inputs], args.trust_before)
