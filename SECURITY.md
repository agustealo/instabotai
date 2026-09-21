# Security

InstabotAI handles Instagram access tokens, optional private-account credentials, reusable private-provider sessions, local execution state, public-web research, and request metadata. Treat those artifacts as security-sensitive.

## Supported security model

The 2.x runtime separates account transport from application authority:

- provider adapters authenticate and perform supported transport operations;
- `IntelligenceEngine` proposes and critiques work but never grants write authority;
- `CampaignRuntime` owns durable scheduling, approval state, leases, and bounded retries;
- `AutomationPolicy` decides whether a planned write is allowed;
- `ActionLedger` atomically reserves quotas and idempotency keys and records provider outcomes;
- `AutomationService` is the canonical write execution path.

A provider, model, browser surface, or campaign worker must not silently bypass approval, confidence, quota, idempotency, or execution controls.

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

## Public-web research and SSRF boundary

Crawl4AI research is treated as outbound network access, not merely content parsing. The generic research path therefore fails closed before browser requests are allowed to reach non-public destinations.

Current protections include:

- HTTP/HTTPS scheme allowlisting;
- rejection of URLs containing userinfo credentials;
- explicit blocked-domain and optional allowed-domain policy;
- rejection of unsafe literal IPv4 and IPv6 destinations;
- DNS resolution before fetch with a requirement that every resolved address be globally routable;
- rejection of loopback, RFC1918/private, link-local, multicast, reserved, and unspecified destinations;
- explicit inspection of IPv4-mapped IPv6, 6to4, Teredo, and NAT64 embedded addresses;
- per-request Chromium route validation, so HTTP(S) navigations, redirects, and subresources are rechecked before continuation;
- final fetched-URL revalidation before research content is accepted.

Meta-owned social domains remain blocked from the generic research crawler by default. Instagram account access belongs to an explicit provider adapter instead.

DNS/IP validation is a required property of future public-web fetchers. A new fetch path must not rely only on hostname string checks, because redirects, DNS rebinding, transition-address formats, and cloud metadata endpoints can otherwise cross the network trust boundary.

## Write retries and ambiguous outcomes

Instagram writes are not automatically replayed when the provider outcome is unknown.

The official Graph provider automatically retries only safe/read methods (`GET`, `HEAD`, and `OPTIONS`). For a POST:

- a transport timeout/error after dispatch is classified as an ambiguous write;
- retryable upstream server failures with an unknown write outcome are classified as ambiguous;
- an unusable response after a dispatched write is classified as ambiguous;
- the provider does not automatically resubmit that POST.

`AutomationService` persists ambiguous writes in `ActionLedger` as non-retryable failures. Reusing the same idempotency key is then rejected, and the ambiguous write continues to count against the relevant daily quota because the remote side may have completed it.

Explicit provider rejection where the outcome is known, such as a rate-limit response, may remain eligible for the outer durable retry policy. Retrying still requires the exact same action identity and payload.

This distinction is intentional: avoiding an accidental duplicate user-visible write takes precedence over automatic recovery from an unknown POST outcome.

## Durable quotas and idempotency

Daily quota checking and action reservation occur in one SQLite `BEGIN IMMEDIATE` transaction. Usage includes in-flight reservations and succeeded actions; ambiguous non-retryable writes are also counted conservatively.

A previously failed action can reuse its idempotency key only when the prior failure is retryable and the immutable action identity and payload match exactly. Reserved, succeeded, and ambiguous non-retryable actions cannot be replayed.

## Reporting a vulnerability

Do not post live credentials, tokens, private session data, or exploitable account details in public discussions. Provide a minimal reproduction with secrets removed and include the affected commit, component, expected behavior, and observed behavior.
