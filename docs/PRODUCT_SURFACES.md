# InstabotAI Product Surfaces

This page is the canonical visual-evidence index for the current InstabotAI revival.

## Screenshot policy

Screenshots in this repository must represent a surface that exists in the current product or a real verification surface produced by the current build. Do not add speculative dashboards, design concepts, placeholder UI, fabricated command output, or screenshots copied from the retired application.

The consumer GUI is still under development. Until it is actually implemented and runnable, the documentation should show the working CLI/runtime and engineering evidence rather than imply that a desktop or web console already ships.

## Runtime diagnostics

**Surface:** `instabotai doctor`  
**Purpose:** inspect runtime configuration without contacting Instagram or a reasoning model.  
**Secrets:** values are reported as configured/not configured; secret values are not printed.  
**Source:** exact-head GitHub Actions Quality Gate #104.

![InstabotAI runtime diagnostics](screenshots/runtime-doctor.svg)

The captured runtime reports the local Ollama provider, `llama3.2:3b`, critic enablement, the decision threshold, official Instagram provider selection, approval enforcement, research limits, and canonical SQLite state path.

## Exact-head release evidence

**Surface:** canonical GitHub Actions Quality Gate  
**Purpose:** prove that the exact proposed source tree installs, type-checks, tests, packages, builds into a container, and starts through the packaged CLI.  
**Source head:** `6f74a5b0fb1ffbc22e235597a06a173d191939d6`  
**Run:** `#104`

![InstabotAI exact-head quality gate](screenshots/quality-gate.svg)

The captured run proves:

- `actions/checkout@v7` and `actions/setup-python@v7` execute successfully;
- Python 3.12.14 package/development installation succeeds;
- Ruff passes;
- strict mypy reports no issues across 19 source files;
- pytest reports 29 passing tests;
- the installed `instabotai doctor` package smoke succeeds;
- the Docker image builds;
- the packaged CLI runs successfully inside the container.

## Operator surface matrix

| Surface | Current status | Contacts external systems | Write authority |
| --- | --- | --- | --- |
| `instabotai doctor` | Implemented | No | None |
| `instabotai ai-check` | Implemented | Configured reasoning model | None |
| `instabotai plan` | Implemented | Configured reasoning model | Produces only a pending action |
| `instabotai decisions` | Implemented | Local SQLite state | Read-only |
| `instabotai profile` | Implemented | Selected Instagram provider | Read-only |
| `instabotai research` | Implemented with research extra | Public web through research policy | None |
| Consumer desktop/web UI | Not shipped yet | N/A | N/A |
| Durable campaign scheduler | In progress | Will consume canonical intelligence/provider authorities | Must not bypass policy |

## Why there is no `ai-check` screenshot here

`ai-check` deliberately performs a genuine model round trip. The canonical CI environment does not run or impersonate a live Ollama/hosted reasoning service, so the repository does not manufacture a successful `ai-check` screenshot. Provider HTTP contracts and failure propagation are covered in tests; a live operator environment supplies the genuine inference proof.

The same rule applies to authenticated Instagram profile screenshots. Documentation should not embed account-specific or credential-dependent output merely to make the README look fuller.

## Updating this page

When a new consumer surface becomes genuinely runnable:

1. capture it from the current exact-head build;
2. remove or redact secrets, tokens, personal account data, and private identifiers;
3. store the capture under `docs/screenshots/`;
4. record the exact head or release that produced it;
5. update this matrix and the README;
6. delete obsolete screenshots when the corresponding UI or command no longer exists.

This keeps the documentation synchronized with the product instead of turning it into a gallery of historical ghosts.
