from __future__ import annotations

import pathlib
import re
import tomllib


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


def test_github_actions_are_commit_pinned_and_use_fixed_runner_series() -> None:
    uses_pattern = re.compile(r"^\s*-?\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)

    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        assert "ubuntu-latest" not in text, workflow
        assert "runs-on: ubuntu-24.04" in text, workflow

        for action, ref in uses_pattern.findall(text):
            if action.startswith("actions/"):
                assert action in PINNED_ACTIONS, f"Unreviewed GitHub action in {workflow}: {action}"
                assert ref == PINNED_ACTIONS[action], (
                    f"Mutable or unexpected action ref in {workflow}: {action}@{ref}"
                )
                assert re.fullmatch(r"[0-9a-f]{40}", ref)


def test_production_container_base_is_digest_pinned() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [line.strip() for line in dockerfile.splitlines() if line.startswith("FROM ")]

    assert from_lines == [f"FROM {DOCKER_BASE}"]


def test_package_uses_current_spdx_license_metadata() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    assert project["license"] == "RPL-1.5"
    assert project["license-files"] == ["LICENSE", "LICENSE_PREMIUM"]


def test_consumer_sdist_does_not_ship_repository_test_suite() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()

    assert "prune tests" in {line.strip() for line in manifest}
