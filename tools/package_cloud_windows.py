"""Validate and archive a Windows build for GitHub Actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import zipfile

from tma_app import APP_NAME, __version__


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_startup(executable):
    with TemporaryDirectory(prefix="tma-cloud-test-") as temporary:
        folder = Path(temporary).resolve()
        result = folder / "startup.json"
        env = os.environ.copy()
        env.update(
            LOCALAPPDATA=str(folder / "profile"),
            QT_QPA_PLATFORM="offscreen",
            ZZZHE_TMA_ACCOUNT_REGISTRY="0",
        )
        subprocess.run(
            [str(executable), "--verify-startup-window", str(result)],
            cwd=folder, env=env, check=True, timeout=90,
        )
        report = json.loads(result.read_text(encoding="utf-8"))
        if report != {"version": __version__, "visible": True, "matplotlib_loaded": False}:
            raise ValueError(f"Unexpected startup report: {report}")


def package_build(dist, output):
    package = (dist / APP_NAME).resolve()
    executable = package / f"{APP_NAME}.exe"
    if not executable.is_file() or not (package / "_internal").is_dir():
        raise ValueError("Windows application or its runtime files are missing")
    if (package / "_internal" / "tma-private").exists():
        raise ValueError("The cloud artifact must not contain local notification resources")
    report = json.loads((package / "release-security.json").read_text(encoding="utf-8-sig"))
    if report["signing_enabled"] or report["signature_status"] != "NotSigned":
        raise ValueError("The cloud build must use the unsigned configuration")
    if report["sha256"] != sha256(executable):
        raise ValueError("Executable hash does not match the build report")
    check_startup(executable)

    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"ZzzHe-TMA-Analysis-{__version__}.zip"
    checksum = archive.with_suffix(".zip.sha256")
    if archive.exists() or checksum.exists():
        raise FileExistsError(f"Output already exists: {archive}")
    with TemporaryDirectory(prefix="tma-zip-", dir=output) as staging:
        pending = Path(staging) / archive.name
        with zipfile.ZipFile(pending, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
            for path in sorted(package.rglob("*")):
                if path.is_file():
                    zipped.write(path, path.relative_to(package.parent).as_posix())
        with zipfile.ZipFile(pending) as zipped:
            bad_file = zipped.testzip()
            if bad_file is not None:
                raise ValueError(f"ZIP integrity check failed: {bad_file}")
        value = sha256(pending)
        pending.rename(archive)
    checksum.write_text(f"{value}  {archive.name}\n", encoding="ascii")
    print(f"{archive.name} · SHA-256 {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path, help="PyInstaller output directory")
    parser.add_argument("output", type=Path, help="directory for ZIP and checksum")
    args = parser.parse_args()
    package_build(args.dist, args.output)
