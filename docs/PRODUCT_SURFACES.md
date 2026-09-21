# InstabotAI Product Surfaces

This page is the canonical visual and operational evidence index for the current InstabotAI revival.

## Evidence policy

Documentation must represent a surface that exists in the current product or a real verification surface produced by the current build. Do not add speculative dashboards, design concepts, placeholder UI, fabricated command output, mock production states, or screenshots copied from the retired application.

The consumer console is a local-first web application backed by the same canonical `InstabotApplication`, `IntelligenceEngine`, `DecisionJournal`, `CampaignRuntime`, provider adapters, research service, policy engine, and durable-state authorities used by the CLI. The GUI must not implement a parallel reasoning or execution stack.

## Consumer console

**Launch:** `instabotai ui`  
**Default bind:** `127.0.0.1:8765`  
**Remote bind:** rejected unless `INSTABOTAI_UI_ALLOW_REMOTE=true` is deliberately enabled.  
**Write authority:** policy-mediated only. Browser actions can request approval or execution of durable campaign jobs, but actual writes continue through the canonical approval, policy, quota, idempotency, ledger, and provider path.

The console currently ships these surfaces.

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

- genuine live-model probe;
- objective authoring;
- typed evidence authoring with stable evidence IDs, source, confidence, and content;
- bounded JSON context;
- planner inference;
- schema validation and allowed-action containment;
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
- copyable decision JSON.

Planning from AI Studio never executes an Instagram write directly.

### Campaigns

The Campaigns surface is the durable automation workspace.

Campaign creation exposes:

- campaign name and business objective;
- supervised or policy-managed mode;
- planning cadence;
- action delay;
- typed manual evidence;
- bounded JSON context;
- optional public-web research before each plan;
- permitted research seed URLs.

Campaign lifecycle controls expose:

- draft state;
- activation;
- pause;
- archive;
- immediate reviewed `plan-now` execution;
- next/last planning time;
- planning failure count;
- current evidence and mode state.

Campaign job controls expose:

- pending approval, scheduled, leased, retry, succeeded, failed, rejected, and cancelled states;
- action type, reason, confidence, schedule, attempt count, decision ID, and job ID;
- explicit approve/reject controls for pending supervised work;
- controlled execution only from executable durable states;
- cancellation of open unleased jobs;
- action payload and durable idempotency-key inspection;
- last execution error;
- provider result inspection;
- explicit post-success business reward and note recording.

A provider accepting an action does not automatically become a positive AI-learning signal. `ExperienceStore` receives campaign feedback only when a business outcome is explicitly recorded after successful provider execution.

The browser does not bypass the scheduler or write spine. Campaign actions still flow through `CampaignRuntime` -> `AutomationService` -> `AutomationPolicy` -> `ActionLedger` -> selected provider.

### Decision Audit

- newest-first durable `DecisionJournal` feed;
- decision ID, objective, score, selected/abstained state, action, timestamp, provider, and model;
- client-side filtering;
- click-through into the full AI decision inspector.

### Adaptive Research

- objective input;
- multiple public-web seed URLs;
- canonical Crawl4AI research service;
- confidence and early-stop state;
- per-page relevance;
- extracted source excerpts;
- policy-blocked URLs;
- failed URLs.

Meta-owned social domains remain blocked by the generic crawler by default. Instagram account data belongs to the explicit provider layer.

### Account

- read-only profile retrieval through the selected Instagram provider;
- official/private provider state;
- credential readiness as configured/not configured only;
- no token or password values returned to the browser;
- current write-approval state.

## Durable worker surface

`instabotai worker` is the recoverable campaign scheduler/execution worker. `instabotai worker --once` runs one deterministic tick for operator verification or external scheduling.

The worker:

1. claims one due campaign with an expiring planning lease;
2. gathers campaign evidence and optional permitted research;
3. calls the single canonical `IntelligenceEngine`;
4. journals the reviewed decision;
5. creates at most one open campaign job;
6. waits for approval when required;
7. claims one due executable job with an expiring execution lease;
8. executes through the canonical write service;
9. persists retry/success/failure state;
10. leaves business-outcome learning to an explicit post-success record.

Stale leases are recoverable. Retries remain bound to the original idempotency identity rather than generating replacement actions.

## Browser/API security boundary

The consumer API adds browser-specific safeguards on top of existing application authorities:

- loopback-only bind by default;
- explicit opt-in for non-loopback binds;
- `Content-Security-Policy` with self-only scripts/styles/connectivity;
- `X-Frame-Options: DENY`;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`;
- restrictive `Permissions-Policy`;
- `Cache-Control: no-store` on `/api/*`;
- bounded AI concurrency;
- separately bounded research concurrency;
- separately bounded campaign planning/execution concurrency;
- structured provider/runtime/campaign errors;
- no browser disclosure of unexpected server stack traces.

The Campaigns frontend is split into self-hosted browser modules rather than growing the original console script into another monolith. The bootstrap preserves the existing core console as `app-core.js`, mounts the campaign shell separately, and guards initialization across `DOMContentLoaded` timing.

## Runtime diagnostics

**Surface:** `instabotai doctor`  
**Purpose:** inspect runtime configuration without contacting Instagram or a reasoning model.  
**Secrets:** values are reported as configured/not configured; secret values are not printed.

![InstabotAI runtime diagnostics](screenshots/runtime-doctor.svg)

The existing diagnostic screenshot remains tied to the real build that produced it. It is not relabeled as a newer capture simply because the runtime has advanced.

## Release evidence

The canonical GitHub Actions Quality Gate proves the proposed source tree installs, type-checks, tests, packages, builds into a container, and starts both the CLI and consumer console.

![InstabotAI quality gate](screenshots/quality-gate.svg)

The gate requires:

- `actions/checkout@v7` and `actions/setup-python@v7`;
- Python 3.12 package/development installation;
- Ruff across `instabotai` and tests;
- strict mypy across production source;
- complete pytest suite;
- consumer static-asset/API regression coverage;
- JavaScript syntax validation through Node when available on the test runner;
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
| `instabotai campaign-create` | Implemented | Local durable state | Creates draft only |
| `instabotai campaign-plan` | Implemented | Reasoning model and optional research | Produces durable job or abstention |
| `instabotai campaign-approve/reject` | Implemented | Local durable state | Human approval state only |
| `instabotai campaign-execute` | Implemented | Selected Instagram provider | Policy-mediated canonical write path |
| `instabotai campaign-outcome` | Implemented | Local durable state | Learning signal only |
| `instabotai worker` | Implemented | Model/research/provider as work requires | Policy-mediated canonical write path |
| Consumer Overview | Implemented | Local runtime only | None |
| Consumer AI Studio | Implemented | Configured reasoning model | Produces only a pending action |
| Consumer Campaigns | Implemented | Model/research/provider as requested | Approval + policy-mediated execution only |
| Consumer Decision Audit | Implemented | Local SQLite state | Read-only |
| Consumer Research | Implemented with research extra | Public web through research policy | None |
| Consumer Account | Implemented | Selected Instagram provider | Read-only |
| Durable campaign scheduler | Implemented | Canonical intelligence/research/provider authorities | Cannot bypass global policy |

## Current verification baseline

The campaign backend and consumer workspace have been validated together on the live PR branch with:

- Ruff green;
- strict mypy green across 26 production source files;
- 44 pytest tests green, including campaign lifecycle/recovery and shipped-JavaScript parser coverage;
- package smoke green;
- Docker build green;
- Docker `instabotai doctor` green;
- Docker consumer-console startup green;
- container `/healthz` probe green.

The PR description and GitHub Actions run are the authority for the latest exact commit SHA. This document intentionally avoids pretending an older screenshot was captured from a newer head.

## Why live authenticated screenshots remain selective

A real `ai-check` requires a reachable model. A real Instagram profile or write requires account credentials. Generic repository documentation must not manufacture a successful provider result, embed private account data, or substitute mock content just to make the product look populated.

When a new consumer-console screenshot is committed, it must be captured from a current runnable build with secrets and personal account information absent or redacted, and its exact head or release must be recorded here.

## Updating this page

When a product surface changes:

1. verify it against the current exact-head build;
2. capture only real product/runtime output;
3. remove or redact secrets, tokens, personal account data, and private identifiers;
4. store visual captures under `docs/screenshots/`;
5. record the exact head or release that produced them;
6. update this matrix and the README;
7. delete obsolete screenshots when the corresponding UI or command no longer exists.

This keeps documentation synchronized with the product instead of turning it into a museum of stale states.
