# Supply-Chain Release Controls

InstabotAI treats repository automation and container ancestry as release inputs, not invisible infrastructure.

## GitHub Actions

Repository workflows use the Ubuntu 24.04 hosted-runner series and pin first-party GitHub actions to reviewed commit SHAs. Human-readable version comments remain beside those pins so intentional upgrades are understandable in review.

`tests/test_supply_chain_contract.py` fails if a repository workflow returns to `ubuntu-latest`, introduces an unreviewed `actions/*` dependency, or replaces a reviewed action commit with a mutable tag.

GitHub-hosted runner image patch revisions are controlled by GitHub and cannot be digest-pinned in workflow YAML. Using `ubuntu-24.04` fixes the operating-system series while action commit pins prevent action code from changing underneath a previously reviewed workflow.

## Production container

The Dockerfile pins the Python 3.12 slim base by digest. Updating that digest is an explicit source change that must pass the normal Quality Gate and the release-artifact burn.

The digest pin fixes the selected base-image manifest. Python package dependencies still follow the version ranges declared in `pyproject.toml`; the release workflow records the resulting artifact and container digests for each published release.

## Python package metadata

The public package declares `RPL-1.5` using current SPDX-based project metadata and explicitly ships both `LICENSE` and `LICENSE_PREMIUM` as license files.

The consumer source distribution excludes the repository test suite. Tests remain in source control and CI, but are not release payload.

## Upgrade policy

Pinned action SHAs and Docker base digests are not permanent. They should be upgraded deliberately when security, compatibility, or platform maintenance requires it. A pin update must be reviewed as a supply-chain change and must pass both the normal Quality Gate and any release workflow triggered by the changed release-critical paths.
