# InstabotAI

InstabotAI is being rebuilt as an adaptive AI decision and Instagram automation runtime with real model inference, evidence-grounded planning, independent critique, durable decision audit, outcome learning, interchangeable account providers, policy-governed writes, durable execution state, and optional Crawl4AI-powered public-web research.

The 2.0 line does **not** carry forward the old mass-engagement Flask bot architecture. The modern runtime is Python 3.12+, typed, test-gated, provider-oriented, and designed so account access, research, AI reasoning, policy, memory, scheduling, and execution remain separate systems.

## Current status

**2.0.0 alpha / active revival**

The current implementation provides the modern runtime, real AI decision engine, provider layer, research layer, durable state, CLI, and quality gates. A consumer UI and higher-level campaign/workflow scheduler are still being built. Do not treat the alpha as unattended production automation.

## Architecture

```text
Public-web sources                    Account/product context
       |                                       |
       v                                       v
+------------------+                   +-------------------+
| AdaptiveResearch |                   | Typed evidence    |
| Crawl4AI         |                   | bounded context   |
+--------+---------+                   +---------+---------+
         |                                       |
         +-------------------+-------------------+
                             v
                    +-------------------+
                    | AI planner model  |
                    | Ollama / hosted   |
                    +---------+---------+
                              v
                    +-------------------+
                    | schema validation |
                    | allowed actions   |
                    +---------+---------+
                              v
                    +-------------------+
                    | deterministic     |
                    | evidence/history  |
                    | utility/risk score|
                    +---------+---------+
                              v
                    +-------------------+
                    | independent critic|
                    +---------+---------+
                              v
                    +-------------------+
                    | DecisionJournal   |
                    | stable decision ID|
                    +---------+---------+
                              v
                    +-------------------+
                    | abstain OR        |
                    | pending action    |
                    +---------+---------+
                              v
                    +-------------------+
                    | policy gate       |
                    | approval/limits   |
                    +---------+---------+
                              v
                    +-------------------+
                    | SQLite ledger     |
                    | idempotency/audit |
                    +---------+---------+
                              v
                    +-------------------+
                    | provider write    |
                    +---------+---------+
                              v
                    +-------------------+
                    | outcome feedback  |
                    | ExperienceStore   |
                    +-------------------+
```

## Genuine AI decision system

The AI layer performs actual language-model inference rather than routing to hard-coded pseudo-intelligence. It supports two interchangeable reasoning providers:

- **Ollama** for local models. This is the default runtime and points to `http://127.0.0.1:11434` unless configured otherwise.
- **OpenAI-compatible** model servers for hosted or self-hosted deployments exposing a chat-completions compatible endpoint.

Model output is never execution authority. The intelligence engine applies a second critic pass, validates responses against typed schemas, rejects actions outside the caller-supplied vocabulary, scores evidence support and risk deterministically, incorporates bounded historical outcomes, and abstains when the final reviewed score does not meet the configured threshold.

Context, evidence, and candidate payloads are explicitly treated as untrusted data rather than instructions. That model-layer prompt-injection defense is followed by typed validation, allowed-action containment, evidence-reference scoring, independent critique, deterministic acceptance thresholds, and downstream policy enforcement.

Every production reasoning result, including abstentions, receives a stable `decision_id` and is persisted in `DecisionJournal`. The journal records the selected action, reviewed score, model/provider identity, critique, uncertainty, explanation, and timestamp. It never stores provider credentials.

Real observed outcomes are stored separately in `ExperienceStore` and influence later scoring only when they are relevant to the current objective. History cannot replace current evidence or bypass policy.

An AI-selected Instagram candidate is converted to a `PlannedAction` with `ApprovalState.PENDING`. The model cannot approve its own write, disable daily limits, bypass idempotency, or call around `AutomationService`.

See `docs/INTELLIGENCE_ARCHITECTURE.md` for the full contract and authority model.

### Instagram providers

InstabotAI has one provider contract and two backends.

**Official provider** is the default and uses Instagram API with Instagram Login on `graph.instagram.com`. Use it for supported professional-account operations when you have Meta application credentials.

**Private provider** is optional and uses the maintained `instagrapi` client. It is intended as a quick-start and authorized-account compatibility path when a user does not yet have an official Meta app. It reuses a persistent session and may require the user to complete Instagram verification normally. InstabotAI does not contain a checkpoint-bypass or anti-abuse evasion engine.

Both providers are behind the same `AutomationService`, policy checks, idempotency ledger, and audit trail. Selecting the private provider does not bypass application limits or approvals.

### Adaptive research

The optional research extra uses Crawl4AI to explore public-web sources adaptively. It ranks discovered links against the research objective, stops when confidence is sufficient, and applies explicit domain policy.

Meta-owned social domains are blocked from this crawler by default. Instagram account data belongs to the provider layer rather than a generic website scraper.

## Installation

Create a Python 3.12+ environment and install the capabilities you need:

```bash
python -m pip install -U pip
python -m pip install -e .
```

Private Instagram provider:

```bash
python -m pip install -e '.[private]'
```

Adaptive public-web research:

```bash
python -m pip install -e '.[research]'
```

Development and validation:

```bash
python -m pip install -e '.[dev]'
```

Extras can be combined, for example `.[private,research,dev]`.

## Quick start

Validate configuration without contacting a model or Instagram:

```bash
instabotai doctor
```

Prove that the configured AI model is genuinely reachable and can return validated structured output:

```bash
instabotai ai-check
```

Read the connected Instagram profile:

```bash
instabotai profile
```

Run adaptive public-web research:

```bash
instabotai research "local fitness marketing trends" \
  --seed https://example.com/fitness-market-report
```

Run genuine AI planning without executing the proposed action:

```bash
instabotai plan "Publish the approved product announcement" \
  --evidence-file ./evidence.json
```

Inspect recent durable AI decisions and abstentions:

```bash
instabotai decisions --limit 25
```

The evidence file is a JSON array of typed evidence records containing `evidence_id`, `source`, `content`, optional `confidence`, and optional `observed_at`. An optional `--context-file` accepts a bounded JSON object with additional campaign/account context. The planning command returns the auditable intelligence decision and a pending action only when the reviewed score passes the configured threshold.

## Configuration

Runtime settings use the `INSTABOTAI_` environment prefix. Secrets should be provided through environment variables or an operator-controlled local secret mechanism, never committed to Git.

### AI runtime

Local Ollama is the default:

```bash
export INSTABOTAI_AI_PROVIDER=ollama
export INSTABOTAI_AI_MODEL='llama3.2:3b'
export INSTABOTAI_AI_BASE_URL='http://127.0.0.1:11434'
```

For an OpenAI-compatible hosted or self-hosted server:

```bash
export INSTABOTAI_AI_PROVIDER=openai_compatible
export INSTABOTAI_AI_MODEL='your-model-id'
export INSTABOTAI_AI_BASE_URL='https://your-model-server.example'
export INSTABOTAI_AI_API_KEY='...'
```

The AI runtime also exposes explicit controls for model timeout, temperature, retries, context size, critic enablement, and the minimum final decision score. `instabotai doctor` reports configuration state without printing the API key. `instabotai ai-check` is the stronger live connectivity and structured-inference proof.

### Official provider

```bash
export INSTABOTAI_INSTAGRAM_PROVIDER=official
export INSTABOTAI_INSTAGRAM_ACCESS_TOKEN='...'
export INSTABOTAI_INSTAGRAM_ACCOUNT_ID='...'
```

`INSTABOTAI_META_GRAPH_API_VERSION` defaults to the version pinned by the current release and can be changed deliberately when upgrading against Meta's API lifecycle.

### Private provider

Install `.[private]`, then configure:

```bash
export INSTABOTAI_INSTAGRAM_PROVIDER=private
export INSTABOTAI_PRIVATE_INSTAGRAM_USERNAME='...'
export INSTABOTAI_PRIVATE_INSTAGRAM_PASSWORD='...'
```

The private adapter stores reusable session state at the configured local session path and attempts to restrict that file to the current user on platforms that support POSIX permissions.

For authorized lab/research instrumentation, `INSTABOTAI_PRIVATE_RESEARCH_MODE=true` enables operator-controlled device/header/session inputs and sanitized request metadata tracing. Security challenges remain Instagram-controlled and are surfaced rather than defeated automatically.

## Write safety and execution guarantees

Instagram write actions are represented as typed `PlannedAction` objects. The canonical write path enforces:

- explicit approval when configured;
- a minimum confidence threshold;
- hard daily action limits;
- transactionally reserved quotas;
- durable idempotency keys;
- succeeded/failed audit state;
- a single provider-independent execution path.

Direct provider objects are integration adapters, not the application orchestration authority.

## Development gates

The canonical GitHub Actions quality gate runs the complete modern source tree:

```bash
python -m ruff check instabotai tests
python -m mypy instabotai
python -m pytest
instabotai doctor
docker build -t instabotai-ci .
docker run --rm instabotai-ci doctor
```

The tests exercise planner/critic behavior, fail-closed invalid output, outcome learning, durable decision journaling, allowed-action containment, actual Ollama and OpenAI-compatible HTTP request contracts, provider failure propagation, policy boundaries, durable action state, and the Instagram provider adapters.

Mypy runs in strict mode. The revival intentionally avoids parallel legacy compatibility logic, production mocks, and silent AI fallbacks. If model reasoning is unavailable or invalid, the intelligence engine abstains.

## Project direction

The next product layer is the durable campaign/workflow scheduler. It will gather live campaign state, research signals, provider observations, policy usage, and previous outcomes and pass that evidence into the single `IntelligenceEngine`. It will not implement a second reasoning stack.

The scheduler will propagate the originating `decision_id` into scheduled work and execution audit metadata so outcomes remain traceable to the exact reasoning record that produced them.

The same objective/evidence/candidate/critique/outcome contracts are intentionally domain-neutral so later product surfaces can reuse the intelligence substrate beyond the initial Instagram workflow without duplicating model orchestration.

## Legal

InstabotAI is independent software and is not affiliated with or endorsed by Instagram or Meta.

The official provider uses supported Meta interfaces. The optional private provider relies on an unofficial client and can be affected by Instagram protocol changes, account trust checks, or platform terms. Users are responsible for operating their accounts and automations appropriately.

See `LICENSE` and `LICENSE_PREMIUM` for the repository's licensing terms.
