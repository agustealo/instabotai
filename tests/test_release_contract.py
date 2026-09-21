from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.release_contract import (
    ProjectMetadata,
    ReleaseContractError,
    build_release_summary,
    expected_tag,
    is_prerelease,
    load_project_metadata,
    validate_distribution_files,
    validate_tag,
)


def write_pyproject(path: Path, *, version: str = "2.0.0a1") -> Path:
    path.write_text(
        "\n".join(
            (
                "[project]",
                'name = "instabotai"',
                f'version = "{version}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def metadata_text(*, version: str = "2.0.0a1") -> str:
    return f"Metadata-Version: 2.4\nName: instabotai\nVersion: {version}\n\n"


def write_wheel(dist: Path, *, version: str = "2.0.0a1") -> Path:
    wheel = dist / f"instabotai-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr(
            f"instabotai-{version}.dist-info/METADATA",
            metadata_text(version=version),
        )
        archive.writestr("instabotai/__init__.py", "")
    return wheel


def write_sdist(
    dist: Path,
    *,
    version: str = "2.0.0a1",
    include_tests: bool = False,
) -> Path:
    sdist = dist / f"instabotai-{version}.tar.gz"
    payload = metadata_text(version=version).encode("utf-8")
    member = tarfile.TarInfo(name=f"instabotai-{version}/PKG-INFO")
    member.size = len(payload)
    with tarfile.open(sdist, mode="w:gz") as archive:
        archive.addfile(member, io.BytesIO(payload))
        if include_tests:
            test_payload = b"def test_release_payload_leak(): pass\n"
            test_member = tarfile.TarInfo(name=f"instabotai-{version}/tests/test_leak.py")
            test_member.size = len(test_payload)
            archive.addfile(test_member, io.BytesIO(test_payload))
    return sdist


def seed_dist(tmp_path: Path, *, version: str = "2.0.0a1") -> tuple[Path, Path, Path]:
    pyproject = write_pyproject(tmp_path / "pyproject.toml", version=version)
    dist = tmp_path / "dist"
    dist.mkdir()
    write_wheel(dist, version=version)
    write_sdist(dist, version=version)
    return pyproject, dist, dist / "SHA256SUMS"


def test_project_metadata_and_tag_contract() -> None:
    project = load_project_metadata(Path("pyproject.toml"))

    assert project == ProjectMetadata(name="instabotai", version="2.0.0a1")
    assert expected_tag(project.version) == "v2.0.0a1"
    assert is_prerelease(project.version)
    validate_tag("v2.0.0a1", project.version)

    with pytest.raises(ReleaseContractError, match="does not match package version"):
        validate_tag("v2.0.0a2", project.version)


def test_release_summary_validates_artifacts_and_writes_sorted_checksums(tmp_path: Path) -> None:
    pyproject, dist, checksums = seed_dist(tmp_path)

    summary = build_release_summary(
        pyproject=pyproject,
        dist_dir=dist,
        tag="v2.0.0a1",
        checksums=checksums,
    )

    assert summary["project"] == "instabotai"
    assert summary["version"] == "2.0.0a1"
    assert summary["prerelease"] is True
    assert [item["filename"] for item in summary["artifacts"]] == [
        "instabotai-2.0.0a1-py3-none-any.whl",
        "instabotai-2.0.0a1.tar.gz",
    ]
    checksum_lines = checksums.read_text(encoding="utf-8").splitlines()
    assert len(checksum_lines) == 2
    assert checksum_lines[0].endswith("  instabotai-2.0.0a1-py3-none-any.whl")
    assert checksum_lines[1].endswith("  instabotai-2.0.0a1.tar.gz")


def test_release_contract_rejects_metadata_version_drift(tmp_path: Path) -> None:
    pyproject = write_pyproject(tmp_path / "pyproject.toml")
    dist = tmp_path / "dist"
    dist.mkdir()
    write_wheel(dist)
    sdist = dist / "instabotai-2.0.0a1.tar.gz"
    payload = metadata_text(version="2.0.0a2").encode("utf-8")
    member = tarfile.TarInfo(name="instabotai-2.0.0a1/PKG-INFO")
    member.size = len(payload)
    with tarfile.open(sdist, mode="w:gz") as archive:
        archive.addfile(member, io.BytesIO(payload))

    with pytest.raises(ReleaseContractError, match="sdist metadata does not match"):
        validate_distribution_files(dist, load_project_metadata(pyproject))


def test_release_contract_rejects_repository_tests_in_sdist(tmp_path: Path) -> None:
    pyproject = write_pyproject(tmp_path / "pyproject.toml")
    dist = tmp_path / "dist"
    dist.mkdir()
    write_wheel(dist)
    write_sdist(dist, include_tests=True)

    with pytest.raises(ReleaseContractError, match="must not contain the repository test suite"):
        validate_distribution_files(dist, load_project_metadata(pyproject))


def test_release_contract_rejects_missing_or_duplicate_artifacts(tmp_path: Path) -> None:
    pyproject = write_pyproject(tmp_path / "pyproject.toml")
    dist = tmp_path / "dist"
    dist.mkdir()
    write_wheel(dist)

    with pytest.raises(ReleaseContractError, match="exactly one wheel and one sdist"):
        validate_distribution_files(dist, load_project_metadata(pyproject))


def test_release_contract_cli_outputs_machine_readable_summary(tmp_path: Path) -> None:
    pyproject, dist, checksums = seed_dist(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_contract.py",
            "--pyproject",
            str(pyproject),
            "--dist",
            str(dist),
            "--tag",
            "v2.0.0a1",
            "--checksums",
            str(checksums),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["expected_tag"] == "v2.0.0a1"
    assert payload["checksums"] == "SHA256SUMS"


def test_stable_version_is_not_marked_prerelease() -> None:
    assert is_prerelease("2.0.0") is False
