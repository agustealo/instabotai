# Documentation Visual Assets

This directory contains repository-owned visual evidence for InstabotAI documentation.

## Current assets

- `consumer-console-overview.png` — real consumer console Overview captured from a running packaged build by `.github/workflows/docs-visual-capture.yml`.
- `architecture-flow.svg` — maintained architecture diagram derived from the current canonical reasoning, campaign, policy, ledger, provider, and outcome boundaries.
- `consumer-trial-readiness.svg` — maintained readiness-flow diagram for static/live checks and their separation from write authority.
- `runtime-doctor.svg` — real packaged runtime diagnostic evidence.
- `quality-gate.svg` — release-quality gate evidence.

Product screenshots must never be fabricated to imply working authenticated behavior. Use the manual **Docs Visual Capture** workflow to refresh the consumer-console PNG from a runnable branch. Authenticated provider screenshots may be added only when private identifiers and secrets are absent or safely redacted and their provenance is recorded in `docs/PRODUCT_SURFACES.md`.

Capture details for the current real-console PNG are recorded in `CAPTURE_PROVENANCE.md`.
