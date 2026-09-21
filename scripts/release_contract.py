#!/usr/bin/env python3
"""Validate InstabotAI release artifacts against the canonical package contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import tomllib
import zipfile
from dataclasses import asdict, dataclass
from email.parser import Parser
from pathlib import Path
from typing import Any


class ReleaseContractError(RuntimeError):
    """Raised when a release candidate violates the packaging contract."""


@dataclass(frozen=True)
class ProjectMetadata:
    name: str
    version: str


@dataclass(frozen=True)
class ArtifactDigest:
    filename: str
    sha256: str
    size_bytes: int


def load_project_metadata(pyproject: Path) -> ProjectMetadata:
    """Read the canonical project name and version from pyproject.toml."""

    with pyproject.open("rb") as handle:
        document = tomllib.load(handle)
    project = document.get("project")
    if not isinstance(project, dict):
        raise ReleaseContractError("pyproject.toml is missing [project]")
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name.strip():
        raise ReleaseContractError("project.name must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise ReleaseContractError("project.version must be a non-empty string")
    return ProjectMetadata(name=name.strip(), version=version.strip())


def normalized_distribution_name(name: str) -> str:
    """Return the wheel/sdist filename form for a distribution name."""

    return re.sub(r"[-_.]+", "_", name).lower()


def expected_tag(version: str) -> str:
    return f"v{version}"


def validate_tag(tag: str, version: str) -> None:
    """Require the release tag to identify the exact packaged version."""

    required = expected_tag(version)
    if tag != required:
        raise ReleaseContractError(
            f"release tag {tag!r} does not match package version {version!r}; expected {required!r}"
        )


def is_prerelease(version: str) -> bool:
    """Identify the PEP 440 prerelease/dev markers used by this project."""

    return bool(re.search(r"(?:a|b|rc)\d+|\.dev\d+", version, flags=re.IGNORECASE))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_fields(text: str) -> tuple[str, str]:
    metadata = Parser().parsestr(text)
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not name or not version:
        raise ReleaseContractError("distribution metadata is missing Name or Version")
    return name.strip(), version.strip()


def validate_wheel(path: Path, project: ProjectMetadata) -> None:
    """Validate wheel filename and embedded Core Metadata."""

    distribution = normalized_distribution_name(project.name)
    expected_filename = f"{distribution}-{project.version}-py3-none-any.whl"
    if path.name != expected_filename:
        raise ReleaseContractError(
            f"unexpected wheel filename {path.name!r}; expected {expected_filename!r}"
        )
    with zipfile.ZipFile(path) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ReleaseContractError(
                "wheel must contain exactly one .dist-info/METADATA file; "
                f"found {len(metadata_names)}"
            )
        text = archive.read(metadata_names[0]).decode("utf-8")
    name, version = _metadata_fields(text)
    if name != project.name or version != project.version:
        raise ReleaseContractError(
            "wheel metadata does not match pyproject.toml: "
            f"Name={name!r}, Version={version!r}"
        )


def validate_sdist(path: Path, project: ProjectMetadata) -> None:
    """Validate source-distribution filename and embedded PKG-INFO."""

    distribution = normalized_distribution_name(project.name).replace("_", "-")
    expected_filename = f"{distribution}-{project.version}.tar.gz"
    if path.name != expected_filename:
        raise ReleaseContractError(
            f"unexpected sdist filename {path.name!r}; expected {expected_filename!r}"
        )
    with tarfile.open(path, mode="r:gz") as archive:
        metadata_members = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")
        ]
        if len(metadata_members) != 1:
            raise ReleaseContractError(
                "sdist must contain exactly one top-level PKG-INFO file; "
                f"found {len(metadata_members)}"
            )
        extracted = archive.extractfile(metadata_members[0])
        if extracted is None:
            raise ReleaseContractError("could not read sdist PKG-INFO")
        text = extracted.read().decode("utf-8")
    name, version = _metadata_fields(text)
    if name != project.name or version != project.version:
        raise ReleaseContractError(
            "sdist metadata does not match pyproject.toml: "
            f"Name={name!r}, Version={version!r}"
        )


def validate_distribution_files(dist_dir: Path, project: ProjectMetadata) -> tuple[Path, Path]:
    """Require exactly one wheel and one sdist for the current project version."""

    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ReleaseContractError(
            "release dist directory must contain exactly one wheel and one sdist; "
            f"found wheels={len(wheels)}, sdists={len(sdists)}"
        )
    wheel = wheels[0]
    sdist = sdists[0]
    validate_wheel(wheel, project)
    validate_sdist(sdist, project)
    return wheel, sdist


def write_checksums(paths: tuple[Path, ...], output: Path) -> tuple[ArtifactDigest, ...]:
    """Write deterministic SHA-256 checksums and return the artifact manifest."""

    output.parent.mkdir(parents=True, exist_ok=True)
    artifacts = tuple(
        ArtifactDigest(
            filename=path.name,
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in sorted(paths, key=lambda item: item.name)
    )
    text = "".join(f"{artifact.sha256}  {artifact.filename}\n" for artifact in artifacts)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(output)
    return artifacts


def build_release_summary(
    *,
    pyproject: Path,
    dist_dir: Path,
    tag: str | None,
    checksums: Path,
) -> dict[str, Any]:
    project = load_project_metadata(pyproject)
    if tag is not None:
        validate_tag(tag, project.version)
    wheel, sdist = validate_distribution_files(dist_dir, project)
    artifacts = write_checksums((wheel, sdist), checksums)
    return {
        "project": project.name,
        "version": project.version,
        "expected_tag": expected_tag(project.version),
        "tag": tag,
        "prerelease": is_prerelease(project.version),
        "artifacts": [asdict(artifact) for artifact in artifacts],
        "checksums": checksums.name,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--tag", default=None, help="Release tag to validate, for example v2.0.0a1")
    parser.add_argument("--checksums", type=Path, default=Path("dist/SHA256SUMS"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = build_release_summary(
            pyproject=args.pyproject,
            dist_dir=args.dist,
            tag=args.tag,
            checksums=args.checksums,
        )
    except (OSError, ReleaseContractError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"release contract failed: {exc}") from exc
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
