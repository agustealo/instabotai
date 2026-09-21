from __future__ import annotations

import pathlib
import re
import tomllib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED_ACTIONS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}
DOCKER_BASE = (
    "python:3.12-slim@sha256:"
    "2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9"
)


def _workflow_files(directory: pathlib.Path) -> list[pathlib.Path]:
    return sorted({*directory.glob("*.yml"), *directory.glob("*.yaml")})


def _yaml_scalar(raw: str) -> str:
    value = raw.strip()
    quoted = re.fullmatch(
        r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)(?:\s+#.*)?",
        value,
    )
    if quoted is not None:
        return quoted.group("value")
    return value.split(" #", 1)[0].strip()


def _workflow_values(text: str, key: str) -> list[str]:
    pattern = re.compile(
        rf"^\s*(?:-\s*)?{re.escape(key)}:\s*(.+?)\s*$",
        re.MULTILINE,
    )
    return [_yaml_scalar(raw) for raw in pattern.findall(text)]


def _validate_workflow(workflow: pathlib.Path) -> None:
    text = workflow.read_text(encoding="utf-8")
    runners = _workflow_values(text, "runs-on")
    assert runners, f"Workflow has no explicit runner: {workflow}"
    for runner in runners:
        assert runner == "ubuntu-24.04", f"Unexpected runner in {workflow}: {runner}"

    for use in _workflow_values(text, "uses"):
        action, separator, ref = use.rpartition("@")
        if action.startswith("actions/"):
            assert separator == "@" and ref, f"Unpinned GitHub action in {workflow}: {use}"
            assert action in PINNED_ACTIONS, f"Unreviewed GitHub action in {workflow}: {action}"
            assert ref == PINNED_ACTIONS[action], (
                f"Mutable or unexpected action ref in {workflow}: {action}@{ref}"
            )
            assert re.fullmatch(r"[0-9a-f]{40}", ref)


def test_github_actions_are_commit_pinned_and_use_fixed_runner_series() -> None:
    workflows = _workflow_files(WORKFLOWS)
    assert workflows, "No GitHub Actions workflows found"
    for workflow in workflows:
        _validate_workflow(workflow)


def test_workflow_guard_handles_yaml_quotes_and_every_runner(tmp_path: pathlib.Path) -> None:
    workflow = tmp_path / "quoted.yaml"
    workflow.write_text(
        """name: Guard fixture
jobs:
  first:
    runs-on: 'ubuntu-24.04'
    steps:
      - uses: \"actions/checkout@v7\"
  second:
    runs-on: ubuntu-22.04
    steps:
      - run: true
""",
        encoding="utf-8",
    )

    assert _workflow_files(tmp_path) == [workflow]
    text = workflow.read_text(encoding="utf-8")
    assert _workflow_values(text, "uses") == ["actions/checkout@v7"]
    assert _workflow_values(text, "runs-on") == ["ubuntu-24.04", "ubuntu-22.04"]
    with pytest.raises(AssertionError, match="Unexpected runner"):
        _validate_workflow(workflow)


def test_production_container_base_is_digest_pinned() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [line.strip() for line in dockerfile.splitlines() if line.startswith("FROM ")]

    assert from_lines == [f"FROM {DOCKER_BASE}"]


def test_package_uses_current_spdx_license_metadata() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    assert project["license"] == "RPL-1.5"
    assert project["license-files"] == ["LICENSE", "LICENSE_PREMIUM"]


def test_manifest_intentionally_prunes_repository_test_suite() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()

    assert "prune tests" in {line.strip() for line in manifest}
