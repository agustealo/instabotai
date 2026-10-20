# InstabotAI Product Surfaces

This page is the canonical visual and operational evidence index for the current InstabotAI 2.x revival.

## Evidence policy

Documentation must represent a surface that exists in the current product or real verification output produced by a runnable build. Do not add speculative dashboards, placeholder UI, fabricated command output, mock production states, credential-dependent success screens presented as generic evidence, or screenshots copied from the retired application.

The consumer console is backed by the same canonical `InstabotApplication`, `IntelligenceEngine`, `DecisionJournal`, `CampaignRuntime`, provider adapters, research service, policy engine, readiness service, and durable-state authorities used by the CLI. The GUI does not implement a parallel reasoning or execution stack.

Explanatory SVG diagrams may simplify a real architecture or control flow, but they must map to current code authorities and must never be presented as runtime screenshots.

## Visual evidence inventory

| Asset | Kind | Purpose | Provenance |
| --- | --- | --- | --- |
| `screenshots/consumer-console-overview.png` | Real product screenshot | Current packaged Overview/readiness surface | Docs Visual Capture run `35649566887`; source head `e947c1380e70210fa5f4f55742f21818368cb916`; product code based on merged `master@d7181ed4eb957538a2a3c93453dcd54d416e9b5c`; capture committed as `0baba46c5e2545e46468d29fc4e91729693172f0` |
| `screenshots/runtime-doctor.svg` | Runtime evidence | Secret-free packaged runtime/config diagnostics | Retained original exact-head evidence; not relabeled as newer output |
| `screenshots/quality-gate.svg` | CI evidence | Release-gate status for its documented baseline | Retained original exact-head evidence; newest workflow/PR remains authoritative |
| `screenshots/architecture-flow.svg` | Explanatory diagram | Current reasoning → durable state → write-control → provider → outcome path | Derived from current canonical runtime authorities |
| `screenshots/consumer-trial-readiness.svg` | Explanatory diagram | Static/live readiness ownership and separation from write authority | Derived from `ConsumerTrialReadinessService` and current API/CLI surfaces |

The real console capture is reproducible. Run the manual **Docs Visual Capture** workflow (`.github/workflows/docs-visual-capture.yml`) against the branch whose UI you intend to document. The workflow installs the package, boots the real local console, waits for `/healthz`, captures the Overview with headless Chrome, and commits the PNG. It does not claim authenticated Instagram or model success.

## Consumer console

**Launch:** `instabotai ui`  
**Default bind:** `127.0.0.1:8765`  
**Remote bind:** rejected in the consumer alpha, even when the legacy `INSTABOTAI_UI_ALLOW_REMOTE` setting is enabled.  
**Write authority:** policy-mediated only. Browser requests continue through durable campaign state, approval, policy, quota, idempotency, ledger, and provider authorities.

### Guided first campaign

Get started now renders the canonical readiness checks it previously computed but
did not display: durable state, AI provider, Instagram provider, write safeguards,
real connectivity and scheduler status. This is read-only and makes blockers and
existing server-side remediation visible, without collecting credentials.

When a user has no campaign, the next step no longer sends them straight into an
unprepared campaign form. It offers three supported paths: **Save source material**
in Evidence Library, **Research my topic** through bounded public-web research,
or **Open AI Studio** to work from a business goal and evidence. An optional
**Open campaign editor** still exists for people who already have approved material.
Returning users with a campaign instead get an existing-campaign link. Route buttons
only navigate; they never create jobs, activate automation, or send Instagram writes.

A late readiness response cannot pull a user off another workspace after they have
already left Overview. Browser acceptance covers desktop/mobile navigation,
visibility of all readiness checks, and confirmation that routing performs no write.

### Overview

![InstabotAI consumer console Overview](screenshots/consumer-console-overview.png)

This is a real packaged-console capture from the source/provenance recorded above. The capture uses non-secret CI-only provider configuration so the static readiness surface can render. It is **not** evidence of authenticated provider or live-model success.

Overview exposes:

- secret-free runtime readiness;
- configured AI provider and model;
- critic and decision-threshold state;
- selected Instagram provider readiness;
- durable-state health;
- research package/profile state;
- global write-approval and bounded write-capacity checks;
- static/live `ConsumerTrialReadiness` status;
- a **Run live checks** control for genuine AI + read-only Instagram probes.

### Guided first run

The **Get started** workspace is assembled from real `/api/readiness`, `/api/consumer`, `/api/worker`, `/api/runtime` and campaign-list data. No UI-only success flags may substitute for those authorities. If required readiness checks fail and the user has no campaigns, the workspace appears automatically.

Provider selectors generate examples for the effective local configuration file. They are **not** live provider switches and never capture credentials in the browser. After local configuration and a runtime restart, the user may explicitly run read-only live model/Instagram checks. A green static check does not imply live connectivity.

Users can create supervised drafts, choose common cadence presets or a bounded custom interval, and edit an existing draft or paused campaign. Editing is rejected by canonical SQLite state when another update won the race, a planning lease is held, or any open job exists. The edit does not mutate previous jobs, provider receipts, or outcome history. Active campaigns must be paused first; archived campaigns are immutable.

The existing Overview screenshot predates this candidate UI work. It should be recaptured after verification and must not be presented as proof that the new journey has passed human usability review.

### Visual hierarchy and progressive disclosure

Daily use surfaces emphasize the meaning of each proposed Instagram action: its headline,
preview text, schedule, authorization and visible failure state. Internal identifiers,
idempotency keys, raw payload and provider diagnostics remain in a keyboard-accessible
**Technical details** disclosure, not removed from the audit surface. Evidence export also lives inside the disclosure and is bound to the stable visible job ID, including when inbox filters reorder the cards. On mobile and desktop
the most important review controls remain visible, and an Execute request is visually marked
as a higher-risk operation. Library entries keep Edit and Mark reviewed visible and tuck
secondary review/deletion controls under **More options**, preserving confirm-before-delete.

The small-text baseline for key controls, metadata and captions has been increased, with
consistent line-height and readable card headings. Playwright checks actual computed font
sizes, responsive overflow, diagnostic access and library action disclosure. These checks do
not establish full WCAG AA, visual quality by human evaluation, or real-world provider success.

### Approval inbox and activity

The approval view distinguishes **AI suggestion**, **human authorization**, **provider execution**, and **observed business impact**. Each pending job explains that Approve authorizes a future policy-governed Instagram write and does not publish immediately. The confirmation names the exact proposed action, campaign, source reason, provider, payload, confidence limitations and consequence. Accessible action names include both action type and campaign.

The Execute button is a real write request, subject to the canonical execution policy. The UI now interprets the job returned by the backend, reporting **Succeeded**, **Failed**, **Retry wait**, or an explicitly nonfinal status rather than assuming that an HTTP 200 means Instagram delivery. Provider delivery is not a business outcome.

The outcome form begins with **no default reward**. Users must deliberately choose a bounded score and provide an observation, with guidance not to guess. Learning still receives feedback only from the existing explicit outcome API. Automated browser tests simulate approval and execution responses but intercept provider writes; they are not evidence of authorized live Instagram delivery.


The Campaigns workspace surfaces an **action inbox before the setup form**. Its stages are derived solely from canonical `CampaignJob.status` values, not frontend guesses:

- **Needs approval:** `pending_approval` actions requiring a deliberate human review.
- **Scheduled:** `scheduled`, `retry_wait`, and `leased` actions.
- **Results & history:** `succeeded`, `failed`, `rejected`, and `cancelled` actions.
- **All:** every job returned by the existing canonical list endpoint.

The inbox filters by campaign, shows plain-language lifecycle explanations, and previews action-specific content for image publishing, comment replies, and hide/unhide moderation. This preview uses backend action data rendered as text rather than untrusted HTML. The existing full-payload disclosure and confirmation dialog remain available for each user-authorized write.

**A provider success is not a business outcome.** Successfully executed work with no recorded reward is counted separately as *Awaiting outcome*, and explicit recording remains required to feed learning. Failed actions are separately visible.

The current API returns at most 200 jobs to this workspace, so the inbox is explicitly a **recent history**, not an exhaustive audit archive. The data is retrieved afresh when the user opens or refreshes Campaigns; there is no claim of real-time push updates. The UI does not replace the decision journal, evidence export, action ledger, backend approvals or execution policy.

### Goal and evidence handoff to supervised campaigns

From AI Studio, a business objective and complete user-supplied evidence can be prepared in the existing Campaigns form without running the planner. The model's proposed Instagram actions are **not** imported as executable work. An explicit confirmation is required before replacing unsaved campaign form inputs. Nothing is saved, activated, approved, or published during the transfer.

Research now offers opt-in per-page selection and extracted-text inspection. Selected HTTP(S) sources are converted to the existing `EvidenceItem` fields: source URL, bounded page text (maximum 12,000 characters), generated evidence ID, and conservative confidence capped at 0.5. At most 20 sources can be transferred in one handoff. Research relevance is not verification of factual truth; the user must inspect each imported source. Seed URLs are prefilled for optional future use, but re-crawling remains off by default.

The transfer exists only in the current browser form until **Create campaign** is deliberately submitted. It does not create a durable reusable research library or substitute for human verification, campaign review, approval, policy, or provider execution.

### Evidence Library

The Evidence Library is a persisted consumer workspace using the canonical SQLite state database and schema migration v4. New entries are **Unverified** whether manually submitted or imported from research. A user can explicitly label an entry Reviewed or Rejected, edit its contents, search by title/source, add tags and review notes, or delete it with an explicit confirmation. Edited source, content or confidence resets the status to Unverified, even when the same request tries to set Reviewed. Review labels reflect a user's judgment and are **not** independent verification.

The API supports bounded paging and optimistic `updated_at` conflict checking. Stale edits and deletes fail rather than overwriting another update. The library stores a unique `library_id`, and a stable `library-{id}` evidence identifier is generated when attaching. An attachment **copies** the existing canonical evidence shape into the current campaign draft/form; later library edits or deletion never rewrite saved campaigns, scheduled work or provider results. Only draft/paused campaigns can be edited through existing canonical checks, and all changes still require explicit save and write approval.

Research selection can also save up to 20 bounded extracts as unverified library records. A partially successful multi-source save is reported honestly, without claiming atomic batch import. Browsing the library never triggers model inference, research crawling, Instagram access or social writes. The new workspace is local-only under the existing loopback consumer console. The library search supports up to 200 entries per page; it is not a substitute for independent source validation or a full browser E2E acceptance trial.

### AI Studio

The AI Studio is an operator surface for the genuine intelligence system, not a decorative chat wrapper.

It provides:

- genuine live-model probe;
- objective authoring;
- typed evidence authoring with stable evidence IDs, source, confidence, and content;
- bounded JSON context;
- planner inference and schema validation;
- allowed-action containment;
- deterministic evidence/history/utility/risk scoring;
- independent critic review;
- abstention inspection;
- final reviewed score and stable decision ID;
- provider/model identity;
- candidate confidence, expected utility, risk, and evidence references;
- critic objections and missing evidence;
- assumptions and uncertainty;
- pending-action payload inspection;
- copyable decision JSON.

Planning from AI Studio never executes an Instagram write directly.

### Campaigns

The Campaigns surface is the durable automation workspace.

Campaign creation exposes campaign name/objective, supervised or policy-managed mode, planning cadence, action delay, typed evidence, bounded context, and optional public-web research seeds.

Lifecycle controls expose draft, active, paused, and archived states; plan-now; next/last planning time; planning failure count; and current campaign evidence/mode.

Job controls expose:

- pending approval, scheduled, leased, retry, succeeded, failed, rejected, and cancelled states;
- action type, reason, confidence, schedule, attempts, decision ID, and job ID;
- explicit approve/reject controls;
- controlled execution only from executable durable states;
- cancellation of open unleased work;
- action payload and idempotency-key inspection;
- execution error and provider-result inspection;
- explicit post-success business reward/note recording.

Provider success is not automatically treated as business success. `ExperienceStore` receives campaign feedback only after an explicit business outcome is recorded.

The browser does not bypass the write spine:

`CampaignRuntime -> AutomationService -> AutomationPolicy -> ActionLedger -> Instagram provider`

![InstabotAI architecture and authority flow](screenshots/architecture-flow.svg)

### Decision Audit

- newest-first durable `DecisionJournal` feed;
- decision ID, objective, reviewed score, selected/abstained state, action, timestamp, provider, and model;
- filtering and click-through into the full AI inspector.

### Adaptive Research

The consumer research surface uses the canonical Crawl4AI-backed service and exposes objective, multiple seed URLs, confidence, early-stop state, per-page relevance, excerpts, blocked URLs, and failed URLs.

The egress boundary includes:

- HTTP/HTTPS-only destinations;
- no URL userinfo credentials;
- blocked-domain and optional allowed-domain policy;
- rejection of unsafe literal IP addresses;
- DNS resolution before fetch, requiring every returned address to be globally routable;
- rejection of loopback, RFC1918/private, link-local, multicast, reserved, and unspecified addresses;
- checks for IPv4-mapped IPv6, 6to4, Teredo, and NAT64 embedded addresses;
- Chromium request routing that revalidates every HTTP(S) navigation, redirect, and subresource before continuing;
- final fetched-URL validation before accepting content.

Meta-owned social domains remain blocked by default. Instagram account data belongs to provider adapters rather than the generic crawler.

### Account

- read-only profile retrieval through the selected Instagram provider;
- official/private provider state;
- credential readiness as configured/not configured only;
- no token or password values returned to the browser;
- current write-approval state.

## Consumer-trial readiness surface

The CLI command `instabotai trial-readiness` and the Overview API use one canonical `ConsumerTrialReadinessService`.

![InstabotAI consumer-trial readiness flow](screenshots/consumer-trial-readiness.svg)

Static checks verify package/runtime identity, truly durable SQLite state, AI configuration, selected-provider credential completeness, research-extra availability according to the chosen trial profile, write approval, and bounded write capacity. Live mode adds genuine model inference plus a read-only Instagram profile request. Readiness reports are secret-free and do not grant write authority.

See [CONSUMER_TRIAL_READINESS.md](CONSUMER_TRIAL_READINESS.md).

## Durable worker surface

`instabotai worker` is the recoverable campaign scheduler/execution worker. `instabotai worker --once` performs one deterministic tick for verification or external scheduling.

The worker claims a due campaign using an expiring lease, gathers evidence/research, calls the canonical intelligence engine, journals the reviewed decision, creates at most one open campaign job, waits for approval when required, claims executable work using an execution lease, writes through the canonical automation service, and persists retry/success/failure state. Business-outcome learning remains explicit after provider success.

Stale leases are recoverable. Retries keep the original action identity rather than minting replacement work.

## Write retry and idempotency boundary

The official Graph provider automatically retries only safe/read methods (`GET`, `HEAD`, and `OPTIONS`). POST requests are single-dispatch at the provider layer.

If a POST times out or otherwise has an unknown remote outcome, it raises `AmbiguousWriteError`. `AutomationService` records that action as a non-retryable failure in `ActionLedger`; the same idempotency key cannot be replayed, and the ambiguous action continues to count against the daily quota because Instagram may already have completed it.

Known explicit rejections such as rate limiting can remain retryable at the outer durable scheduler layer, but only for the exact same action identity/payload.

Daily quota checking and reservation occur atomically in SQLite and include in-flight reservations, succeeded actions, and ambiguous non-retryable writes.

## Browser/API security boundary

The consumer API adds browser-specific safeguards on top of application authorities:

- loopback-only bind, rejecting unauthenticated remote access even with legacy opt-in;
- self-only CSP for scripts/styles/connectivity;
- `X-Frame-Options: DENY`;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`;
- restrictive `Permissions-Policy`;
- `Cache-Control: no-store` on `/api/*`;
- independently bounded AI, research, and campaign concurrency;
- structured provider/runtime/campaign errors;
- no browser disclosure of unexpected server stack traces.

Campaign browser code remains modular: the original core console is preserved separately from campaign bootstrap/UI modules, and startup is guarded across `DOMContentLoaded` timing.

## Runtime diagnostics

**Surface:** `instabotai doctor`  
**Purpose:** inspect runtime configuration without contacting Instagram or a reasoning model.  
**Secrets:** reported only as configured/not configured.

![InstabotAI runtime diagnostics](screenshots/runtime-doctor.svg)

The screenshot remains tied to the build that actually produced it. It is not silently relabeled as a newer capture.

## Release evidence

The canonical GitHub Actions Quality Gate proves the proposed source tree installs, type-checks, tests, packages, builds into a container, and starts both the CLI and consumer console.

![InstabotAI quality gate](screenshots/quality-gate.svg)

The current gate requires:

- Python 3.12 package/development installation;
- Ruff across `instabotai` and tests;
- strict mypy across production source;
- complete pytest suite;
- consumer static-asset/API regressions;
- installed `instabotai doctor` smoke;
- FastAPI application creation smoke;
- a freshly built wheel installed in a clean virtual environment;
- clean-wheel `trial-readiness` smoke;
- Docker image build;
- packaged `doctor` and `trial-readiness` inside Docker;
- consumer-console startup inside Docker;
- successful container `/healthz` response.

## Operator surface matrix

| Surface | Status | External systems | Write authority |
| --- | --- | --- | --- |
| `instabotai doctor` | Implemented | No | None |
| `instabotai trial-readiness` | Implemented | No in static mode | None |
| `instabotai trial-readiness --live` | Implemented | Reasoning model + Instagram provider read | None |
| `instabotai ai-check` | Implemented | Reasoning model | None |
| `instabotai plan` | Implemented | Reasoning model | Pending action only |
| `instabotai decisions` | Implemented | Local SQLite | Read-only |
| `instabotai profile` | Implemented | Instagram provider | Read-only |
| `instabotai research` | Implemented with research extra | Public web through hardened egress policy | None |
| `instabotai campaign-create` | Implemented | Local durable state | Draft only |
| `instabotai campaign-plan` | Implemented | Model + optional research | Durable job or abstention |
| `instabotai campaign-approve/reject` | Implemented | Local durable state | Approval state only |
| `instabotai campaign-execute` | Implemented | Instagram provider | Canonical policy-mediated path |
| `instabotai campaign-outcome` | Implemented | Local durable state | Learning signal only |
| `instabotai worker` | Implemented | Model/research/provider as work requires | Canonical policy-mediated path |
| Consumer Overview | Implemented | Local runtime; optional live probes | None |
| Consumer AI Studio | Implemented | Reasoning model | Pending action only |
| Consumer Campaigns | Implemented | Model/research/provider as requested | Approval + canonical execution |
| Consumer Decision Audit | Implemented | Local SQLite | Read-only |
| Consumer Research | Implemented | Public web through hardened egress policy | None |
| Consumer Account | Implemented | Instagram provider | Read-only |

## Current consumer-trial verification baseline

Consumer-trial readiness code was validated on exact candidate `12f93f1d5647ff173c19fb3dd88d94a1ca425638` with Quality Gate #153 before merge to `master@d7181ed4eb957538a2a3c93453dcd54d416e9b5c`:

- Ruff green;
- strict mypy green across 27 production source files;
- **66 pytest tests passed**;
- package smoke green;
- clean-wheel install and readiness smoke green;
- Docker build, packaged runtime readiness, and consumer `/healthz` green.

The PR description and newest exact-head GitHub Actions run remain the authority if later commits advance the branch.

## Why authenticated screenshots remain selective

A real `ai-check` requires a reachable model. Real Instagram profile/write evidence requires account credentials. Repository documentation must not manufacture provider success, embed private account data, or substitute mock content just to make the product look populated.

The current Overview screenshot intentionally proves the packaged UI and static readiness presentation only. Authenticated provider/model screenshots should be added only from controlled real trials with secrets and private account identifiers absent or redacted.

## Updating visual evidence

When a product surface changes:

1. verify it against the current exact-head build;
2. for the Overview, run the manual **Docs Visual Capture** workflow rather than drawing a replacement screenshot;
3. capture only real product/runtime output;
4. remove or redact secrets and private identifiers;
5. store visual captures under `docs/screenshots/`;
6. record the exact source head/run/release that produced them;
7. update this matrix and README;
8. remove obsolete visual evidence when the corresponding surface no longer exists.
