# InstabotAI

InstabotAI 2.x is an adaptive AI decision and Instagram automation runtime built around real model inference, evidence-grounded planning, independent critique, durable decision audit, explicit outcome learning, interchangeable account providers, policy-governed writes, recoverable campaign scheduling, and optional Crawl4AI-powered public-web research.

The current line does **not** preserve the retired mass-engagement Flask bot as a compatibility layer. The modern runtime is Python 3.12+, typed, test-gated, provider-oriented, and deliberately separates account access, public-web research, AI reasoning, campaign state, approval, policy, memory, scheduling, idempotency, and provider execution.

## Current status

**2.0.0 alpha / consumer-trial hardening**

Implemented today:

- genuine model-backed `IntelligenceEngine` with planner + independent critic;
- typed evidence grounding, deterministic adjudication, abstention, and durable decision journal;
- Ollama and OpenAI-compatible reasoning providers;
- official Instagram Graph provider plus optional maintained `instagrapi` private provider;
- adaptive Crawl4AI research with hardened public-network egress policy;
- canonical `AutomationService`, policy engine, transactional daily quotas, and durable idempotency;
- durable campaign scheduler, approval queue, ownership leases, bounded retries, and explicit outcome learning;
- CLI and local-first FastAPI consumer console;
- canonical static/live consumer-trial readiness authority shared by CLI and GUI;
- exact-head Ruff, strict mypy, pytest, wheel, Docker, readiness, and live-console gates.

The alpha should still be operated under supervision while authenticated provider behavior is validated during consumer trials. AI output is never write authority.

## Consumer console

Launch the GUI:

```bash
instabotai ui
```

The console binds to `127.0.0.1:8765` by default. A non-loopback bind is rejected unless `INSTABOTAI_UI_ALLOW_REMOTE=true` is deliberately configured.

![InstabotAI consumer console Overview](docs/screenshots/consumer-console-overview.png)

> **Real product capture.** This Overview image was produced by the packaged application itself in GitHub Actions, not by a mock or design file. The reproducible capture path is `.github/workflows/docs-visual-capture.yml`; capture provenance is recorded in [docs/PRODUCT_SURFACES.md](docs/PRODUCT_SURFACES.md).

The GUI uses the same canonical application/runtime authorities as the CLI. Shipped surfaces are:

- **Overview**: secret-free runtime plus the canonical static/live consumer-trial readiness report.
- **AI Studio**: live model probe, typed evidence, bounded context, planner + critic execution, scores, abstention, and pending-action inspection.
- **Campaigns**: campaign creation/lifecycle, supervised or policy-managed mode, cadence/delay, optional research-before-plan, approval/rejection, controlled execution, retry/error/provider inspection, idempotency inspection, and explicit business-outcome feedback.
- **Decision Audit**: durable `DecisionJournal` browsing and filtering.
- **Adaptive Research**: Crawl4AI-backed objective/seed research with confidence, relevance, blocked/failed URLs, and hardened destination validation.
- **Account**: read-only profile retrieval through the selected Instagram provider with secret-free readiness state.

Campaign execution from the GUI is not a shortcut around policy. Executable work still flows through:

```text
CampaignRuntime
  -> AutomationService
  -> AutomationPolicy
  -> ActionLedger
  -> Instagram provider
```

Provider success is not automatically business success. AI learning receives campaign reward only after an explicit post-success outcome is recorded.

## Architecture

![InstabotAI architecture and authority flow](docs/screenshots/architecture-flow.svg)

The model is deliberately boxed in by non-model authorities. Evidence and optional public-web research feed `IntelligenceEngine`; model output is validated and deterministically adjudicated, journaled, persisted into durable campaign state, and can reach a provider only through approval, policy, quota, and idempotency controls. Explicit observed outcomes, not provider success alone, feed bounded future learning.

See [docs/INTELLIGENCE_ARCHITECTURE.md](docs/INTELLIGENCE_ARCHITECTURE.md) for scoring, prompt-injection containment, model-provider contracts, and decision-journal details.

## Genuine intelligence authority

The AI layer performs actual language-model inference. It is not a hard-coded routing facade.

Supported reasoning providers:

- **Ollama** for local models, defaulting to `http://127.0.0.1:11434`.
- **OpenAI-compatible** hosted or self-hosted chat-completions servers.

Model output is treated as untrusted proposal data. The intelligence engine validates structured responses, contains actions to an allowed vocabulary, scores evidence/history/utility/risk outside the model, runs an independent critic, journals the result, and abstains when support is insufficient.

Every finalized decision or abstention receives a stable `decision_id`. AI-selected Instagram work becomes a pending `PlannedAction`; the model cannot approve itself, weaken limits, bypass idempotency, change provider security, or call around `AutomationService`.

`ExperienceStore` receives only explicit observed business outcomes and contributes a bounded relevance-weighted prior to later decisions. Historical reward cannot replace current evidence or policy.

## Consumer-trial readiness

The CLI and Overview share one `ConsumerTrialReadinessService` rather than separate checklists.

```bash
# Local/static checks: package, durable state, configuration and guardrails
instabotai trial-readiness

# Add genuine model inference + read-only Instagram profile probes
instabotai trial-readiness --live

# Treat Crawl4AI support as required for this trial profile
instabotai trial-readiness --require-research
```

![InstabotAI consumer-trial readiness flow](docs/screenshots/consumer-trial-readiness.svg)

Static readiness rejects transient `:memory:` state for trials, validates selected-provider credentials, checks the research extra according to the selected trial profile, requires the global write-approval guardrail, and verifies bounded non-zero write capacity. Live mode adds a genuine model round trip and a real read-only provider profile request. Readiness never grants write authority.

See [docs/CONSUMER_TRIAL_READINESS.md](docs/CONSUMER_TRIAL_READINESS.md).

## Durable campaigns and worker

Campaigns store objective, evidence, bounded context, optional research seeds, cadence, action delay, mode, planning state, and failure state. Only one open action per campaign is permitted at a time.

Planning and execution use expiring ownership leases, allowing stale work to recover after crashes without creating parallel ownership. Supervised campaigns require explicit approval. Policy-managed mode can omit campaign-level approval only when global policy also permits it.

Run the worker continuously or for one deterministic tick:

```bash
instabotai worker
instabotai worker --once
```

A typical flow is:

```text
claim campaign -> research/evidence -> planner/critic -> journal
-> durable job -> approval -> claim execution lease
-> canonical write path -> provider result -> explicit business outcome
```

## Instagram providers

InstabotAI exposes one application provider contract with two backends.

**Official provider** is the default and uses Instagram API with Instagram Login on `graph.instagram.com` for supported professional-account operations.

**Private provider** is optional and uses maintained `instagrapi` as an authorized-account compatibility path. It may require normal Instagram verification and can be affected by platform protocol changes. InstabotAI does not implement checkpoint defeat, CAPTCHA bypass, signature theft, or anti-abuse evasion.

Both providers remain behind the same application policy, idempotency, and audit authorities.

### Safe retry semantics

The official Graph provider automatically retries only safe/read methods: `GET`, `HEAD`, and `OPTIONS`.

POST writes are single-dispatch at the provider layer. If a timeout, transport failure, unusable response, or retryable server failure leaves the remote write outcome unknown, the provider raises `AmbiguousWriteError`. That action is persisted as a **non-retryable** failure; its idempotency key cannot be replayed and it continues to consume the daily quota because the remote side may already have completed the write.

Known explicit rejections, such as rate limiting, can remain retryable at the durable outer layer, but only for the exact same action identity and payload.

## Adaptive research and SSRF boundary

Install the `research` extra to enable Crawl4AI-backed public-web research. The service ranks links against the objective, bounds pages, tracks confidence, and can stop early.

Research is also an outbound network boundary. The current implementation enforces:

- HTTP/HTTPS-only URLs;
- rejection of URL userinfo credentials;
- blocked domains and optional allowlisted domains;
- rejection of unsafe literal IPv4/IPv6 addresses;
- DNS resolution before fetch, requiring **every** resolved address to be globally routable;
- rejection of loopback, RFC1918/private, link-local, multicast, reserved, and unspecified destinations;
- inspection of IPv4-mapped IPv6, 6to4, Teredo, and NAT64 embedded addresses;
- Chromium route validation before every HTTP(S) navigation, redirect, or subresource continues;
- final fetched-URL revalidation before content is accepted.

Meta-owned social domains remain blocked from the generic crawler by default. Instagram account data belongs to provider adapters, not website scraping.

## Transactional quotas and idempotency

`ActionLedger.reserve()` performs quota checking and reservation in one SQLite `BEGIN IMMEDIATE` transaction. Usage counts in-flight reservations and successful actions; ambiguous non-retryable writes are counted conservatively as well.

A failed action can reuse an idempotency key only when the prior failure is explicitly retryable and the immutable action identity/payload match exactly. Reserved, succeeded, and ambiguous non-retryable actions cannot be replayed.

## Installation

```bash
python -m pip install -U pip
python -m pip install -e .
```

Optional capabilities:

```bash
python -m pip install -e '.[private]'
python -m pip install -e '.[research]'
python -m pip install -e '.[dev]'
```

Extras can be combined, for example `.[private,research,dev]`.

## Quick start

```bash
# GUI
instabotai ui

# Consumer-trial gate
instabotai trial-readiness

# Secret-free runtime diagnostics
instabotai doctor

# Genuine model connectivity + structured inference proof
instabotai ai-check

# Read selected Instagram account
instabotai profile

# Public-web research
instabotai research "local fitness marketing trends" \
  --seed https://example.com/fitness-market-report

# One reviewed plan, no execution
instabotai plan "Publish the approved product announcement" \
  --evidence-file ./evidence.json

# Durable campaign
instabotai campaign-create "Product launch" \
  "Publish evidence-grounded launch content" \
  --evidence-file ./evidence.json \
  --mode supervised
instabotai campaign-activate CAMPAIGN_ID
instabotai campaign-plan CAMPAIGN_ID
instabotai campaign-jobs --campaign-id CAMPAIGN_ID
instabotai campaign-approve JOB_ID
instabotai campaign-execute JOB_ID
instabotai campaign-outcome JOB_ID --reward 0.8 --note "Measured business outcome"
```

## Configuration

Settings use the `INSTABOTAI_` prefix. Secrets belong in environment variables or another operator-controlled secret mechanism, never in Git.

### UI

```bash
export INSTABOTAI_UI_HOST='127.0.0.1'
export INSTABOTAI_UI_PORT='8765'
export INSTABOTAI_UI_OPEN_BROWSER='true'
```

Non-loopback binds require explicit opt-in:

```bash
export INSTABOTAI_UI_ALLOW_REMOTE='true'
```

### AI

```bash
export INSTABOTAI_AI_PROVIDER=ollama
export INSTABOTAI_AI_MODEL='llama3.2:3b'
export INSTABOTAI_AI_BASE_URL='http://127.0.0.1:11434'
```

OpenAI-compatible server:

```bash
export INSTABOTAI_AI_PROVIDER=openai_compatible
export INSTABOTAI_AI_MODEL='your-model-id'
export INSTABOTAI_AI_BASE_URL='https://your-model-server.example'
export INSTABOTAI_AI_API_KEY='...'
```

### Official Instagram provider

```bash
export INSTABOTAI_INSTAGRAM_PROVIDER=official
export INSTABOTAI_INSTAGRAM_ACCESS_TOKEN='...'
export INSTABOTAI_INSTAGRAM_ACCOUNT_ID='...'
```

### Private Instagram provider

```bash
export INSTABOTAI_INSTAGRAM_PROVIDER=private
export INSTABOTAI_PRIVATE_INSTAGRAM_USERNAME='...'
export INSTABOTAI_PRIVATE_INSTAGRAM_PASSWORD='...'
```

Install `.[private]` before using that backend. Authorized research-mode credential bundles are also supported; see the readiness and provider documentation rather than duplicating secrets into repository files.

## Consumer/API security

The local console adds browser-specific protections including loopback-only binding by default, explicit remote-bind opt-in, self-only CSP, frame denial, `nosniff`, no-referrer policy, restrictive permissions policy, no-store API responses, bounded AI/research/campaign concurrency, structured secret-free errors, and no unexpected stack traces returned to the browser.

See [SECURITY.md](SECURITY.md) for the network, credential, write-retry, and idempotency boundaries.

## Development gates

The canonical gate runs lint, strict typing, the complete test suite, installed-package smoke, clean-wheel readiness smoke, Docker build/runtime readiness smoke, and live consumer-console health verification.

Consumer-trial readiness code was proven on exact candidate `12f93f1d5647ff173c19fb3dd88d94a1ca425638` by Quality Gate #153 before merge to `master@d7181ed4eb957538a2a3c93453dcd54d416e9b5c`:

- Ruff green;
- strict mypy green across 27 production source files;
- **66 tests passed**;
- package smoke green;
- clean-wheel install + `trial-readiness` green;
- Docker build + `doctor` + `trial-readiness` green;
- containerized consumer-console `/healthz` green.

The newest exact-head workflow and PR description remain authoritative if later documentation or code commits advance the branch.

## Verified product surfaces

Repository screenshots must come from real product/runtime evidence, never mocked success states.

| Visual | What it proves |
| --- | --- |
| ![Consumer console Overview](docs/screenshots/consumer-console-overview.png) | The current packaged consumer UI boots and renders its real Overview/readiness surface. |
| ![InstabotAI packaged runtime diagnostics](docs/screenshots/runtime-doctor.svg) | Secret-free packaged runtime/config diagnostics. |
| ![InstabotAI quality gate](docs/screenshots/quality-gate.svg) | Release-gate evidence for the documented validation baseline. |
| ![InstabotAI architecture flow](docs/screenshots/architecture-flow.svg) | Canonical reasoning, durable state, write-control, provider, and learning boundaries. |
| ![InstabotAI readiness flow](docs/screenshots/consumer-trial-readiness.svg) | Static/live readiness ownership and the separation from write authority. |

See [docs/PRODUCT_SURFACES.md](docs/PRODUCT_SURFACES.md) for provenance, the operator/evidence matrix, and screenshot policy.

## Project direction

The core orchestration substrate is now in place. Remaining release work should focus on authenticated real-provider consumer-trial evidence, operator ergonomics, observability, migration/upgrade reliability, deployment hardening, and real-world burn testing rather than adding another automation architecture.

## Legal

InstabotAI is independent software and is not affiliated with or endorsed by Instagram or Meta.

The official provider uses supported Meta interfaces. The optional private provider relies on an unofficial client and can be affected by Instagram protocol changes, account trust checks, or platform terms. Users are responsible for operating their accounts and automations appropriately.

See `LICENSE` and `LICENSE_PREMIUM` for licensing terms.
