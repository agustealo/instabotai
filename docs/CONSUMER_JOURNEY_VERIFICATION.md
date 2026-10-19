# Consumer journey verification

This checklist is intentionally from the perspective of a first-time Instagram campaign owner.
Source-level tests and automated CI do **not** establish that a human can complete these journeys.

## 1. First run with no configured services

- Start `instabotai ui` on a machine with durable local state and no Instagram credentials.
- Verify **Get started** is discovered automatically when mandatory readiness is incomplete and no campaigns exist.
- Confirm each blocker shows a concrete next action, with no stack traces, bearer tokens, or passwords.
- The AI provider and Instagram provider selectors must generate local configuration examples only.
  A changed selector must never silently change the actual running provider or claim connectivity.
- Copy the configuration path/example, populate it locally and restart. Confirm the loaded
  runtime and readiness report reflect the actual selected providers.
- Run live connection checks deliberately. They must never publish, reply to, or moderate content.

## 2. Understand the state of automation

- Verify the Overview and Get started workspaces expose the embedded scheduler's running state.
- Simulate a stopped worker and a failed worker tick. The UI must not claim active campaigns
  will progress or disclose sensitive provider exception messages.
- Ensure error notifications persist until dismissed, rather than disappearing before
  a user can read them.

## 3. Create a first supervised campaign

- Enter a meaningful name and goal; use approved evidence or enable research with seed URLs.
- Leave both evidence and seed URLs empty: receive a useful validation error, not a 500.
- Choose **Once a day**, **Twice a day**, **Every 6 hours**, **Once a week** and
  **Custom interval**. Confirm each selection produces a valid canonical minute cadence.
- Create a draft, then verify persistence after a full process restart.
- Confirm that draft creation alone never executes an Instagram write.

## 4. Edit a campaign safely

- Edit a draft, then a paused campaign without open jobs. Verify objective, cadence,
  evidence, context, and research settings survive restart.
- Open the same campaign in two browser tabs; save from one, then attempt to save the
  stale version from the other. The second must receive a clear conflict, never overwrite.
- Attempt editing an active campaign, archived campaign, campaign with an active
  planning lease, and paused campaign with pending/leased/scheduled work. Each must fail
  closed through the canonical API and leave existing jobs and outcomes unchanged.
- Cancel editing: the form must return to creation mode without writing any changes.

## 5. Supervised execution and evidence

- Activation, approving, rejecting, executing, cancelling, and archiving must each
  reveal enough context before a high-impact write, including the planned action payload.
- If runtime or policy details are unavailable, the Execute control must fail closed.
- Real provider success must never be conflated with business outcomes. Record reward
  only through the explicit post-success outcome flow.
- Verify rollback/restart behavior, provider ambiguity, idempotency and retry safety,
  and no implicit authorization through AI output.

## 6. UX, accessibility, and release gates

- Complete all journeys using keyboard only, including the confirmation dialog's Escape
  and Go back behavior; ensure visible focus and screen-reader labels.
- Test desktop, tablet and 360px mobile layouts, including horizontal navigation,
  error messages, oversized goals, and long campaign names.
- Test reduced-motion settings and normal-text contrast to WCAG AA targets.
- Run Ruff, strict mypy, pytest, shipped JavaScript syntax, and canonical
  containerized health verification on the exact branch head.
- Before consumer release, obtain human acceptance and authorized live Instagram/model
  evidence. A green CI gate alone does not prove real-world provider functionality.
- No distribution or consumer release packaging should be triggered solely by this change.

## Authority boundaries

`InstabotApplication` remains the application service; `CampaignRuntime` owns
planning/execution; `CampaignStore` owns atomic campaign updates; the SQLite
open-job/lease gates and optimistic `updated_at` version check are authoritative.
The browser is a client of these rules and cannot approve or execute a write by itself.
