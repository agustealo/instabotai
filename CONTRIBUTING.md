# Contributing to InstabotAI

InstabotAI 2.x is a clean rebuild around provider adapters, typed domain models, policy-governed execution, durable state, and adaptive research. Contributions should strengthen that architecture rather than recreate legacy mass-action scripts or parallel authorities.

## Development setup

Use Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'
```

Install optional capabilities when working on them:

```bash
python -m pip install -e '.[dev,private]'
python -m pip install -e '.[dev,research]'
```

## Required local gate

Before proposing a change, run the same core validation enforced in GitHub Actions:

```bash
python -m ruff check instabotai tests scripts
python -m mypy instabotai
python -m pytest
instabotai doctor
```

Do not weaken strict typing, policy checks, supply-chain pinning, or tests to make a change pass.

## Architectural rules

1. **One canonical write path.** Instagram writes belong behind `AutomationService`, `AutomationPolicy`, and `ActionLedger`.
2. **Provider adapters are transport boundaries.** Official and private Instagram providers implement shared capabilities; application decisions do not belong inside provider clients.
3. **No duplicate persistence authority.** Durable execution state belongs in the canonical state layer.
4. **Research and account access stay separate.** Crawl4AI is for policy-approved public-web research. Instagram account access belongs to an Instagram provider.
5. **Fail closed.** Unsupported actions, invalid configuration, quota exhaustion, missing approval, or ambiguous write state must not silently proceed.
6. **No hidden mock production behavior.** Test doubles belong in tests. Runtime fallbacks must represent real supported behavior.
7. **No credential files in Git.** Secrets and local session artifacts must remain outside source control.
8. **Private-provider compatibility is optional.** Do not make unofficial protocol behavior the application core.
9. **Do not automate security-checkpoint defeat.** Verification and account challenges remain controlled by Instagram and the account owner.
10. **Keep the package modular.** Prefer small typed services and explicit interfaces over monolithic scripts or global mutable clients.
11. **Keep release inputs explicit.** GitHub actions used by repository workflows must be commit-pinned, CI uses the fixed Ubuntu 24.04 runner series, and the production Docker base must stay digest-pinned unless a reviewed upgrade intentionally changes it.

## Changes to provider behavior

Provider changes should include tests for the contract they modify. When adding a capability, determine whether it is supported by both providers. If not, the unsupported provider should fail explicitly rather than pretend success.

For private-provider changes, preserve reusable session/device context and propagate challenge, feedback, throttling, and authentication failures clearly. Do not add mechanisms whose purpose is to disguise automation or evade platform controls.

## Changes to automation

Every new write action needs:

- an explicit `ActionType`;
- a typed payload contract;
- a policy decision path;
- a hard limit where repeated execution could be harmful;
- idempotency behavior;
- durable success/failure audit state;
- tests for rejection and success cases.

## Changes to research

Research changes must preserve domain access policy, bounded crawling, deterministic normalization, and explicit failure reporting. New ranking or extraction logic should have focused tests and should not turn Instagram private account access into generic scraping.

## Pull requests

Keep each pull request internally coherent and leave the branch in a fully gated state. Describe architectural effects, migration implications, provider differences, and validation evidence. If a change intentionally drops a legacy behavior, say so explicitly rather than carrying dead compatibility code indefinitely.

## Security reports

Do not publish credentials, session cookies, access tokens, private request traces, or account-identifying data in pull requests, commits, screenshots, or discussions. Redact sensitive information before sharing diagnostic output.
