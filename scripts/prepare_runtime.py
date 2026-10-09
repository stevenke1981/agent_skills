"""Prepare the shared Windows runtime once; client machines install nothing."""
from __future__ import annotations
import argparse
import importlib.metadata
from pathlib import Path
import shutil
import urllib.request
import uuid
import zipfile

import yaml
import skills_db as db
from manager_core import safe_archive_name


def publish_folder(source: Path, destination: Path):
    expected = {path.relative_to(source).as_posix(): db.file_digest(path) for path in source.rglob("*") if path.is_file()}
    if destination.exists():
        actual = {path.relative_to(destination).as_posix(): db.file_digest(path) for path in destination.rglob("*") if path.is_file()}
        if actual != expected:
            raise RuntimeError("Existing runtime differs; use a new versioned folder")
        return
    staging = destination.with_name(destination.name + ".incoming-" + uuid.uuid4().hex)
    shutil.copytree(source, staging)
    db.rename_with_retry(staging, destination)
    for name, digest in expected.items():
        if db.file_digest(db.relative_path(destination, name)) != digest:
            raise RuntimeError("Shared runtime readback failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, default=Path(db.NAS))
    args = parser.parse_args()
    config = db.read_json(db.BASE / "config/runtime.json")
    if yaml.__version__ != config["yaml_version"]:
        raise RuntimeError("Build with the pinned PyYAML version")
    working = db.BASE / ".work/runtime-build"
    working.mkdir(parents=True, exist_ok=True)
    archive_path = working / ("python-" + config["python_version"] + ".zip")
    if not archive_path.exists():
        with urllib.request.urlopen(config["python_url"], timeout=40) as response:
            content = response.read(32 * 1024 * 1024 + 1)
        if len(content) > 32 * 1024 * 1024 or db.digest(content) != config["python_download_sha256"]:
            raise RuntimeError("Official Python download checksum mismatch")
        archive_path.write_bytes(content)
    if db.file_digest(archive_path) != config["python_download_sha256"]:
        raise RuntimeError("Python archive checksum mismatch")
    python_root = working / config["python_folder"]
    python_root.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            target = db.relative_path(python_root, safe_archive_name(entry.filename))
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(entry))
    (python_root / "python313._pth").write_bytes(("python313.zip\n.\n../" + config["yaml_folder"] + "\n../../scripts\n").encode())
    vendor = working / config["yaml_folder"]
    yaml_root = Path(yaml.__file__).parent
    for path in yaml_root.rglob("*.py"):
        target = vendor / "yaml" / path.relative_to(yaml_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    distribution = importlib.metadata.distribution("PyYAML")
    licenses = [path for path in distribution.files if str(path).endswith("/licenses/LICENSE")]
    if len(licenses) != 1:
        raise RuntimeError("PyYAML license could not be located")
    shutil.copyfile(distribution.locate_file(licenses[0]), vendor / "PyYAML-LICENSE.txt")
    runtime = db.filesystem_path(args.library) / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    publish_folder(python_root, runtime / config["python_folder"])
    publish_folder(vendor, runtime / config["yaml_folder"])
    manifest = {"schema": 1, "python": config, "files": []}
    for folder in [config["python_folder"], config["yaml_folder"]]:
        for path in sorted((runtime / folder).rglob("*")):
            if path.is_file():
                manifest["files"].append({"path": path.relative_to(runtime).as_posix(), "sha256": db.file_digest(path), "size": path.stat().st_size})
    existing = runtime / "manifest.json"
    if existing.exists() and db.read_json(existing) != manifest:
        raise RuntimeError("Existing runtime manifest differs")
    db.write_json(existing, manifest)
    print("Shared runtime prepared and read back: " + str(runtime), flush=True)


if __name__ == "__main__":
    main()
