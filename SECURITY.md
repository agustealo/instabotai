# Security

InstabotAI handles Instagram access tokens, optional private-account credentials, reusable private-provider sessions, local execution state, and request metadata. Treat those artifacts as secrets.

## Supported security model

The 2.x runtime separates account transport from application authority:

- provider adapters authenticate and perform supported transport operations;
- `AutomationPolicy` decides whether a planned write is allowed;
- `ActionLedger` reserves quotas and idempotency keys and records outcomes;
- `AutomationService` is the canonical write execution path.

A provider must not silently bypass approval, confidence, quota, or idempotency controls.

## Credentials

Do not commit:

- Instagram access tokens;
- usernames/passwords;
- session or cookie state;
- credential bundles;
- challenge codes;
- replacement passwords;
- proxy credentials;
- private request traces containing account identifiers.

Use environment variables or another operator-controlled secret mechanism. The optional private provider attempts to restrict persisted session and trace files to the current user on platforms that support POSIX file permissions.

If a secret is committed, rotate or revoke it. Removing it from the current tree does not remove it from Git history.

## Private provider

The private provider is optional compatibility infrastructure. It may be affected by Instagram protocol changes, account trust decisions, throttling, or verification challenges.

InstabotAI does not implement automated checkpoint defeat, CAPTCHA solving, platform-signature extraction, device-fingerprint rotation for evasion, or other mechanisms whose purpose is to bypass Instagram security controls.

Authorized research mode can accept operator-supplied session/device/header inputs and verification values and can record sanitized request metadata for debugging. Verification decisions remain platform-controlled.

## Public-web research

Crawl4AI research is bounded by domain policy and page limits. Meta-owned social domains are blocked from the generic research crawler by default. Instagram account access belongs to a provider adapter instead.

Any future fetcher that accepts arbitrary URLs must preserve SSRF protections for server-side downloads, including scheme validation, DNS resolution checks, redirect revalidation, response-size limits, and content-type validation where applicable.

## Reporting a vulnerability

Do not post live credentials, tokens, private session data, or exploitable account details in public discussions. Provide a minimal reproduction with secrets removed and include the affected commit, component, expected behavior, and observed behavior.
