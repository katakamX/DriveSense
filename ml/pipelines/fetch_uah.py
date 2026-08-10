"""Fetch UAH-DriveSet into the gitignored `data/` tree.

UAH-DriveSet is **not** available from a stable public URL. The dataset page
(http://www.robesafe.uah.es/personal/eduardo.romera/uah-driveset/) gates the
download behind a licence agreement: a terms checkbox plus an email address,
POSTed to `download.php`. That agreement is the user's to give, so this script
never posts it. Instead it takes the archive you obtained after accepting the
licence, and does everything downstream of that reproducibly:

    # after accepting the licence in a browser
    python -m pipelines.fetch_uah --archive ~/Downloads/UAH-DRIVESET-v1.zip

    # or, if you hold a direct URL the licence gate has already granted you
    python -m pipelines.fetch_uah --url https://.../UAH-DRIVESET-v1.zip

Licence terms that outlive this script (see `data/README.md`): academic and
non-commercial use only, **no redistribution** of the dataset or modified
versions, and any work using it must cite Romera et al., ITSC 2016. This is
why no recording is ever committed to this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipelines.adapters.uah import find_recordings, parse_recording_name

REPO_ROOT = Path(__file__).resolve().parents[2]
DEST_ROOT = REPO_ROOT / "data" / "raw" / "uah-driveset"
ARCHIVE_DIR = DEST_ROOT / "_archive"
MANIFEST_PATH = DEST_ROOT / "MANIFEST.json"

# Pinned on the first successful fetch, then committed, so every later fetch
# proves it got the same bytes. `None` means "not yet pinned" — the first run
# prints the digest it computed and tells you to commit it.
EXPECTED_SHA256: str | None = "ebb4b59c2913a6ef62d4f578a2792b310fe970a5d84c489092f06deeb57f3884"

DOWNLOAD_CHUNK_BYTES = 1 << 20


class FetchError(RuntimeError):
    """The dataset could not be fetched, verified or extracted."""


@dataclass(frozen=True)
class ArchiveInfo:
    path: Path
    sha256: str
    size_bytes: int
    source: str


# --- Digest ---------------------------------------------------------------


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(DOWNLOAD_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def verify_digest(actual: str) -> None:
    """Compare against the pinned digest, or report the first one seen."""
    if EXPECTED_SHA256 is None:
        print(
            f"\nNo expected digest is pinned yet. This archive is:\n"
            f"    sha256 = {actual}\n"
            f"Set EXPECTED_SHA256 in {Path(__file__).name} to that value and commit it, "
            f"so later fetches are verified.\n"
        )
        return
    if actual != EXPECTED_SHA256:
        raise FetchError(
            "archive digest mismatch — refusing to use it\n"
            f"  expected {EXPECTED_SHA256}\n"
            f"  actual   {actual}"
        )
    print(f"digest verified: {actual}")


# --- Acquire --------------------------------------------------------------


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    print(f"downloading {url}")

    with urllib.request.urlopen(url) as response:  # noqa: S310 - user-supplied URL by design
        total = int(response.headers.get("Content-Length") or 0)
        written = 0
        with partial.open("wb") as handle:
            while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                handle.write(chunk)
                written += len(chunk)
                if total:
                    print(f"\r  {written / total:6.1%} ({written >> 20} MiB)", end="", flush=True)
    print()
    partial.replace(destination)


def acquire(url: str | None, archive: Path | None) -> ArchiveInfo:
    """Get the archive on disk, downloading only if it is not already there."""
    if archive is not None:
        if not archive.is_file():
            raise FetchError(f"{archive} not found")
        local = ARCHIVE_DIR / archive.name
        if local.resolve() != archive.resolve():
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive, local)
        source = str(archive)
    elif url is not None:
        local = ARCHIVE_DIR / Path(urllib.parse.urlparse(url).path).name
        if local.is_file():
            print(f"archive already present: {local}")
        else:
            download(url, local)
        source = url
    else:
        raise FetchError("pass --url or --archive")

    return ArchiveInfo(
        path=local,
        sha256=sha256_of(local),
        size_bytes=local.stat().st_size,
        source=source,
    )


# --- Extract --------------------------------------------------------------


def _is_within(base: Path, target: Path) -> bool:
    return base.resolve() in target.resolve().parents or base.resolve() == target.resolve()


def extract(archive: Path, destination: Path) -> None:
    """Extract into `destination`, refusing entries that escape it.

    A downloaded archive is untrusted input: an entry named `../../etc/x`
    would otherwise write outside the data tree ("zip slip").
    """
    destination.mkdir(parents=True, exist_ok=True)
    print(f"extracting {archive.name} -> {destination}")

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if not _is_within(destination, destination / member):
                    raise FetchError(f"archive entry escapes destination: {member!r}")
            zf.extractall(destination)
        return

    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            for member_name in tf.getnames():
                if not _is_within(destination, destination / member_name):
                    raise FetchError(f"archive entry escapes destination: {member_name!r}")
            tf.extractall(destination, filter="data")
        return

    if archive.suffix.lower() == ".7z":
        if shutil.which("7z") is None:
            raise FetchError(
                f"{archive.name} is a 7-Zip archive and no `7z` executable is on PATH. "
                "Install p7zip / 7-Zip, or extract it manually into "
                f"{destination} and re-run with --skip-extract."
            )
        subprocess.run(["7z", "x", str(archive), f"-o{destination}", "-y"], check=True)
        return

    raise FetchError(f"unrecognised archive format: {archive.name}")


# --- Manifest -------------------------------------------------------------


def git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip()


def inventory(root: Path) -> dict[str, Any]:
    """Summarise what was actually extracted, using the adapter's own parser."""
    recordings = find_recordings(root)
    drivers: set[str] = set()
    behaviours: set[str] = set()
    road_types: set[str] = set()
    for directory in recordings:
        meta = parse_recording_name(directory.name)
        drivers.add(meta.driver_id)
        behaviours.add(meta.behaviour)
        road_types.add(meta.road_type)

    return {
        "recording_count": len(recordings),
        "drivers": sorted(drivers),
        "behaviours": sorted(behaviours),
        "road_types": sorted(road_types),
        "recording_ids": [d.name for d in recordings],
    }


def write_manifest(info: ArchiveInfo, destination: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "dataset": "UAH-DriveSet",
        "citation": "Romera, Bergasa, Arroyo. Need Data for Driver Behaviour Analysis? "
        "Presenting the Public UAH-DriveSet. IEEE ITSC 2016.",
        "licence": "Academic / non-commercial use only; redistribution prohibited.",
        "source": info.source,
        "archive_name": info.path.name,
        "sha256": info.sha256,
        "size_bytes": info.size_bytes,
        "fetched_at": datetime.now(UTC).isoformat(),
        "extracted_to": str(destination.relative_to(REPO_ROOT)),
        "fetched_by_git_sha": git_sha(),
        **inventory(destination),
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def already_fetched(expected_sha: str | None) -> bool:
    """True when a previous run left a verified, non-empty extraction in place."""
    if expected_sha is None or not MANIFEST_PATH.is_file():
        return False
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(manifest.get("sha256") == expected_sha and manifest.get("recording_count"))


# --- Entry point ----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch, verify and extract UAH-DriveSet into data/raw/uah-driveset.",
        epilog="The dataset is licence-gated; obtain the archive yourself, then pass --archive.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path, help="path to an already-downloaded archive")
    source.add_argument("--url", help="direct URL the licence gate has granted you")
    parser.add_argument("--force", action="store_true", help="re-extract even if already present")
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="archive is already unpacked; just verify and inventory",
    )
    args = parser.parse_args(argv)

    try:
        if already_fetched(EXPECTED_SHA256) and not args.force:
            print(f"already fetched and verified; {MANIFEST_PATH} is current. Use --force to redo.")
            return 0

        info = acquire(args.url, args.archive)
        verify_digest(info.sha256)

        if not args.skip_extract:
            extract(info.path, DEST_ROOT)

        manifest = write_manifest(info, DEST_ROOT)
        print(f"\nwrote {MANIFEST_PATH}")
        print(json.dumps(manifest, indent=2))

        if manifest["recording_count"] == 0:
            print(
                "\nWARNING: no recording directories were recognised. Check whether the "
                "extracted layout differs from the expected "
                "<timestamp>-<distance>km-D<n>-<BEHAVIOUR>-<ROAD> naming.",
                file=sys.stderr,
            )
        return 0

    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
