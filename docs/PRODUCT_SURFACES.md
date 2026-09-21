# InstabotAI Product Surfaces

This page is the canonical visual and operational evidence index for the current InstabotAI revival.

## Evidence policy

Documentation in this repository must represent a surface that exists in the current product or a real verification surface produced by the current build. Do not add speculative dashboards, design concepts, placeholder UI, fabricated command output, or screenshots copied from the retired application.

The consumer console is now implemented and shipped by the package. It is a local-first web application backed by the same canonical `InstabotApplication`, `IntelligenceEngine`, `DecisionJournal`, provider adapters, research service, and policy authorities used by the CLI. The GUI must not implement a parallel reasoning or execution stack.

## Consumer console

**Launch:** `instabotai ui`  
**Default bind:** `127.0.0.1:8765`  
**Remote bind:** rejected unless `INSTABOTAI_UI_ALLOW_REMOTE=true` is deliberately enabled.  
**Write authority:** none directly; AI-created writes remain pending and must continue through approval, policy, idempotency, and the canonical execution service.

The consumer console currently ships these product surfaces:

### Overview

- secret-free runtime readiness;
- configured AI provider and model;
- critic and decision-threshold state;
- Instagram provider readiness;
- decision-journal status;
- research budget and confidence target;
- write-policy status and approval requirement.

### AI Studio

The AI Studio is a full operator surface for the genuine intelligence system rather than a chat-shaped wrapper around hard-coded automation.

It provides:

- a genuine live-model `ai-check` probe;
- objective authoring;
- dynamic typed evidence authoring with stable evidence IDs, source, confidence, and content;
- bounded JSON context authoring;
- real planner inference;
- schema validation and allowed-action containment in the canonical intelligence engine;
- deterministic evidence/history/utility/risk scoring;
- independent critic review;
- abstention inspection;
- final reviewed score;
- stable decision ID;
- provider/model identity;
- candidate confidence, expected utility, risk, and evidence references;
- critic support, critic risk, objections, and missing evidence;
- assumptions and uncertainty;
- pending-action payload inspection;
- decision JSON copy for debugging/audit.

Planning from the GUI never executes an Instagram write directly.

### Decision Audit

- newest-first durable `DecisionJournal` feed;
- decision ID, objective, score, selected/abstained state, action, timestamp, provider, and model;
- client-side filtering;
- click-through from a journal row into the full AI decision inspector.

### Adaptive Research

- business/research objective input;
- multiple public-web seed URLs;
- canonical Crawl4AI research service;
- confidence and early-stop state;
- per-page relevance;
- extracted source excerpts;
- policy-blocked URLs;
- failed URLs.

Meta-owned social domains continue to be blocked by the generic crawler by default. Instagram account data belongs to the explicit provider layer.

### Account

- read-only profile retrieval through the selected Instagram provider;
- official/private provider selection state;
- credential readiness shown only as configured/not configured;
- no token or password values returned to the browser;
- current write-approval state.

## Browser/API security boundary

The consumer API adds browser-specific safeguards on top of the existing application authorities:

- loopback-only bind by default;
- explicit opt-in required for non-loopback binds;
- `Content-Security-Policy` with self-only scripts/styles/connectivity;
- `X-Frame-Options: DENY`;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`;
- restrictive `Permissions-Policy`;
- `Cache-Control: no-store` on `/api/*`;
- bounded concurrent AI operations;
- separately bounded concurrent research operations;
- structured provider/runtime errors;
- unexpected server exceptions do not expose stack traces to the browser.

## Runtime diagnostics

**Surface:** `instabotai doctor`  
**Purpose:** inspect runtime configuration without contacting Instagram or a reasoning model.  
**Secrets:** values are reported as configured/not configured; secret values are not printed.

![InstabotAI runtime diagnostics](screenshots/runtime-doctor.svg)

The diagnostic output remains backward-compatible with the original 2.0 revival surface while the GUI receives a richer nested runtime snapshot through `/api/runtime`.

## Release evidence

The canonical GitHub Actions Quality Gate proves the proposed source tree installs, type-checks, tests, packages, builds into a container, and starts both the CLI and consumer console.

![InstabotAI exact-head quality gate](screenshots/quality-gate.svg)

The current gate requires:

- `actions/checkout@v7` and `actions/setup-python@v7`;
- Python 3.12 package/development installation;
- Ruff across `instabotai` and tests;
- strict mypy across production source;
- the complete pytest suite;
- installed `instabotai doctor` package smoke;
- consumer FastAPI application import/creation smoke;
- Docker image build;
- packaged `instabotai doctor` inside Docker;
- actual consumer console startup inside Docker;
- successful HTTP response from the running container's `/healthz` endpoint.

## Operator surface matrix

| Surface | Current status | Contacts external systems | Write authority |
| --- | --- | --- | --- |
| `instabotai doctor` | Implemented | No | None |
| `instabotai ai-check` | Implemented | Configured reasoning model | None |
| `instabotai plan` | Implemented | Configured reasoning model | Produces only a pending action |
| `instabotai decisions` | Implemented | Local SQLite state | Read-only |
| `instabotai profile` | Implemented | Selected Instagram provider | Read-only |
| `instabotai research` | Implemented with research extra | Public web through research policy | None |
| Consumer Overview | Implemented | Local runtime only | None |
| Consumer AI Studio | Implemented | Configured reasoning model | Produces only a pending action |
| Consumer Decision Audit | Implemented | Local SQLite state | Read-only |
| Consumer Research | Implemented with research extra | Public web through research policy | None |
| Consumer Account | Implemented | Selected Instagram provider | Read-only |
| Durable campaign scheduler | In progress | Will consume canonical intelligence/provider authorities | Must not bypass policy |

## Why live authenticated screenshots remain selective

`ai-check` performs a genuine model round trip. An authenticated Instagram profile requires real account credentials. Generic repository documentation must not manufacture a successful provider result or embed private account data just to make a screenshot more colorful.

When a consumer-console screenshot is committed, it must be captured from a current runnable build with secrets and personal account information absent or redacted, and its exact head or release must be recorded here.

## Updating this page

When a product surface changes:

1. verify it against the current exact-head build;
2. capture only real product/runtime output;
3. remove or redact secrets, tokens, personal account data, and private identifiers;
4. store visual captures under `docs/screenshots/`;
5. record the exact head or release that produced them;
6. update this matrix and the README;
7. delete obsolete screenshots when the corresponding UI or command no longer exists.

This keeps the documentation synchronized with the product instead of turning it into a gallery of historical ghosts.
