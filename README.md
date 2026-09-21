# InstabotAI

InstabotAI is being rebuilt as an adaptive Instagram intelligence and automation runtime with two interchangeable account providers, policy-governed writes, durable execution state, and optional Crawl4AI-powered public-web research.

The 2.0 line does **not** carry forward the old mass-engagement Flask bot architecture. The modern runtime is Python 3.12+, typed, test-gated, provider-oriented, and designed so account access, research, decision logic, policy, and execution remain separate systems.

## Current status

**2.0.0 alpha / active revival**

The current implementation provides the new runtime foundation and CLI. A consumer UI and higher-level campaign/workflow layer are still being built. Do not treat the alpha as unattended production automation.

## Architecture

```text
Public-web sources                 Instagram account
       |                                  |
       v                                  v
+------------------+             +-------------------+
| AdaptiveResearch |             | Provider adapter  |
| Crawl4AI         |             | official/private  |
+--------+---------+             +---------+---------+
         |                                 |
         v                                 |
+------------------+                       |
| normalized       |                       |
| research signal  |                       |
+--------+---------+                       |
         |                                 |
         +------------+--------------------+
                      v
              +---------------+
              | planned action|
              +-------+-------+
                      v
              +---------------+
              | policy gate   |
              | approval      |
              | confidence    |
              | daily limits  |
              +-------+-------+
                      v
              +---------------+
              | SQLite ledger |
              | idempotency   |
              | audit state   |
              +-------+-------+
                      v
              +---------------+
              | provider write|
              +---------------+
```

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

Validate the active configuration without performing an Instagram write:

```bash
instabotai doctor
```

Read the connected profile:

```bash
instabotai profile
```

Run adaptive public-web research:

```bash
instabotai research "local fitness marketing trends" \
  --seed https://example.com/fitness-market-report
```

## Configuration

Runtime settings use the `INSTABOTAI_` environment prefix. Secrets should be provided through environment variables or an operator-controlled local secret mechanism, never committed to Git.

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

The canonical GitHub Actions quality gate runs:

```bash
python -m ruff check ...
python -m mypy instabotai
python -m pytest
instabotai doctor
```

Mypy runs in strict mode. The revival is intentionally avoiding parallel legacy compatibility logic and silent mock fallbacks.

## Project direction

The next product layers are a durable workflow/campaign engine, richer Instagram read models and media support, intelligence/ranking services, event ingestion, observability, and a modern consumer-facing control surface. Those layers will build on the provider/policy/ledger authority already established here rather than reintroducing mass-action scripts.

## Legal

InstabotAI is independent software and is not affiliated with or endorsed by Instagram or Meta.

The official provider uses supported Meta interfaces. The optional private provider relies on an unofficial client and can be affected by Instagram protocol changes, account trust checks, or platform terms. Users are responsible for operating their accounts and automations appropriately.

See `LICENSE` and `LICENSE_PREMIUM` for the repository's licensing terms.
