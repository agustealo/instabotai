# Release Process

InstabotAI releases are built from an exact repository ref and must preserve one authority chain from source commit to Python artifacts, container image, checksums, and GitHub Release metadata.

The release workflow does not replace the normal Quality Gate. A release candidate must first be merged through the project gate and the exact `master` commit must complete its post-merge Quality Gate successfully.

## Current release line

The package currently declares:

```text
2.0.0a1
```

The matching release tag is therefore:

```text
v2.0.0a1
```

The release workflow rejects any tag that does not exactly match `v` plus the version stored in `pyproject.toml`.

## Release authority

`.github/workflows/release.yml` is the canonical build-and-publish path for release artifacts.

For a tag-triggered release it verifies that:

- the tag exactly matches the package version;
- the tagged commit is contained in `master`;
- no GitHub Release already exists for that tag;
- the source distribution and wheel both contain metadata matching `pyproject.toml`;
- the built wheel installs into a clean virtual environment;
- the installed wheel can run `doctor` and static consumer-trial readiness against durable state;
- the production Docker image builds from the same release ref;
- the Docker image runs as a non-root runtime user;
- the container can run the canonical `doctor` command;
- SHA-256 checksums are generated for the wheel and source distribution;
- the same container is published under both the package-version tag and the exact source-SHA tag in GHCR;
- the final wheel, source distribution, checksums, release-contract report, wheel/runtime proofs, container proof, and published container digest are attached to the GitHub Release.

A manual `workflow_dispatch` run performs the build and release-proof steps but does not publish a GHCR image or create a GitHub Release. Use that mode to burn the release machinery before creating a tag.

## Repository protection prerequisite

`master` must be protected before consumer release work is considered complete. The repository configuration should require pull requests and the `Quality Gate` check before changes can land on `master`.

This is a GitHub repository setting, not an application-code concern. The codebase must not pretend that a workflow file can substitute for server-side branch protection.

At minimum, the repository rule should prevent direct unreviewed pushes that bypass the required quality gate. If repository rulesets are used instead of classic branch protection, they should enforce the same invariant.

## Preparing a release

1. Confirm the intended version in `pyproject.toml`.
2. Merge the release candidate only after exact-head PR Quality Gate success.
3. Confirm the post-merge Quality Gate is green on the exact `master` commit.
4. Run the **Release** workflow manually from that exact commit and inspect the uploaded release-proof artifact.
5. Confirm no unresolved release or security blocker remains.
6. Create the matching annotated tag from the proven `master` commit.
7. Push the tag once.
8. Confirm the tag-triggered Release workflow completes successfully.
9. Verify the created GitHub Release and GHCR image references.
10. Retain the release checksums and trial evidence according to the operator's release-data policy.

Example for the current alpha:

```bash
git fetch origin master --tags
git checkout master
git pull --ff-only origin master
git tag -a v2.0.0a1 -m "InstabotAI 2.0.0a1"
git push origin v2.0.0a1
```

Do not move or reuse a release tag after publication. If a released artifact is defective, increment the package version and publish a new tag.

## Release artifacts

The GitHub Release contains the release build outputs and proof files from `dist/`.

The Python artifact integrity file is:

```text
SHA256SUMS
```

It contains deterministic SHA-256 hashes for exactly the wheel and source distribution. These hashes detect artifact changes, but they are not a cryptographic signature and must not be described as authenticated signer identity.

The release contract report is:

```text
release-contract.json
```

It records the package name/version, expected tag, prerelease classification, artifact filenames, sizes, and SHA-256 digests.

The published container digest is recorded in:

```text
CONTAINER_IMAGE
```

For a tag `v2.0.0a1`, the workflow publishes container references equivalent to:

```text
ghcr.io/agustealo/instabotai:2.0.0a1
ghcr.io/agustealo/instabotai:sha-<exact-git-sha>
```

The workflow deliberately does not publish a floating `latest` image for prereleases.

## Python package registry

The current release authority creates GitHub Release artifacts and GHCR images. It does **not** publish to PyPI.

PyPI publication should be added only when the project has an explicitly configured trusted-publisher identity and the package-name ownership has been verified. Repository tokens or long-lived PyPI API keys should not be introduced merely to make the first alpha easier to publish.

## Consumer-trial relationship

A green release proves that the exact package and container can be built, validated, and published from the tagged source commit. It does not prove real Instagram credentials, a live model endpoint, or a successful real-world provider write.

Those remain consumer-trial concerns and should be demonstrated with:

```bash
instabotai trial-readiness --live
instabotai trial-evidence JOB_ID --live --output ./trial-evidence-live.json
instabotai trial-evidence-verify ./trial-evidence-live.json
```

Release proof and trial evidence are complementary. Neither should be stretched into an authority it does not own.
