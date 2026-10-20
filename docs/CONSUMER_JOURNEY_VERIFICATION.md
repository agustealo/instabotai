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

## 5. Goal and research handoff

- Enter a goal in AI Studio, continue to a supervised campaign form, and confirm the goal
  transfers without running the planner or creating an Instagram action.
- Select specific Research pages, inspect extracted text, and verify that only explicitly
  selected sources are imported with original URLs and conservative confidence.
- Try empty selections, an invalid URL, more than 20 sources, and a 13,000-character page.
  Confirm the handoff rejects or bounds each case without dropping information silently.
- Cancel the handoff while another campaign is being edited. Verify unsaved work remains.
- Verify source selection by keyboard, mobile overflow, and form focus after navigation.
- Verify all transfer data remains unsaved until a human creates the campaign draft, after
  which activation and Instagram-action approval must still occur separately.

## 6. Persistent evidence library

- From Research, select two permitted source pages and choose **Save selected to library**.
  Verify they are persisted, initially unverified, and available after restarting the runtime.
- Search by title/source and page through results; tag and revise an entry with the original
  source text intact. Mark it Reviewed, then modify its source or confidence and verify
  its review automatically resets to Unverified.
- Open the same entry in two tabs: the later stale save and deletion must receive a conflict.
  Reject an entry and verify the UI refuses to attach it to a campaign.
- Select saved evidence, enter a goal, and prepare a new supervised campaign form. Nothing
  is created, planned or published until the user explicitly saves the campaign and later
  approves an action.
- Attach saved evidence to an existing draft or paused campaign. Check that the user is
  taken to the existing editor and must save; active/archived campaigns cannot be edited.
- Edit or delete the library record after it has been saved in a campaign and verify the
  campaign evidence snapshot and any queued jobs remain unchanged.
- Validate keyboard, screen reader, responsive layout, empty states and clear failure
  messages for unavailable local storage, partial imports and invalid entries.

## 7. Supervised execution and evidence

- Activation, approving, rejecting, executing, cancelling, and archiving must each
  reveal enough context before a high-impact write, including the planned action payload.
- If runtime or policy details are unavailable, the Execute control must fail closed.
- Real provider success must never be conflated with business outcomes. Record reward
  only through the explicit post-success outcome flow.
- Verify rollback/restart behavior, provider ambiguity, idempotency and retry safety,
  and no implicit authorization through AI output.

## 8. Approval inbox and activity usability

- With no pending approvals, the default **Needs approval** stage must state clearly
  that nothing needs authorization, even if scheduled or historical jobs exist.
- With pending approvals, verify action-specific preview content and full-payload
  confirmation for image publishing, comment replies, and hide/unhide moderation.
  Backend policy remains the only source of permission to execute.
- Confirm Scheduled groups scheduled, retry-wait, and leased jobs while Results & history
  groups succeeded, failed, rejected, and cancelled jobs.
- Confirm newest-first ordering, per-campaign filtering, refresh, counts, and empty states.
- For a succeeded job with no observed outcome, verify **Awaiting outcome** is
  displayed; provider success must never be described as business success.
- Use keyboard and screen readers with the filter buttons, `aria-pressed` state,
  campaign selector, and visibly labeled outcome fields.
- The list endpoint is limited to recent entries (up to 200 jobs). Check that the
  UI never presents this as an exhaustive audit history or a live streaming feed.

## 9. Approval decisions, provider status and meaningful outcomes

- Read the action-specific preview and confirm that every Approve, Reject, Execute and
  Cancel dialog names the consequence, campaign, target, original AI reason, confidence
  limitations, destination provider, schedule and complete action payload.
- Inspect the same queue from keyboard and a screen reader. Every action must be identified
  with its campaign and action type, not simply repeated "Approve" labels.
- Escape and Go back must return without sending any approval or provider-write request.
  Approve must permit a later policy-governed write, never describe itself as publication.
- Intercept simulated successful, failed, retry-wait and nonterminal execute responses. The
  UI must not claim Instagram delivery when the returned status is failed or retry-wait.
- In Results & history, the business score starts blank. Browser validation must require
  a deliberate 0–1 result and an observation note before submission, without guessing
  a default outcome from a provider success.
- Test focus and dynamic queue changes across mobile, desktop, and reduced-motion layouts.
- Approval browser tests intercept provider-affecting API routes. Run authorized real-provider
  trials and human WCAG/screen-reader review separately before consumer release.

## 10. UX, accessibility, and release gates

- Complete all journeys using keyboard only, including the confirmation dialog's Escape
  and Go back behavior; ensure visible focus and screen-reader labels.
- Test desktop, tablet and 320px/375px mobile layouts, including the expandable menu,
  error messages, oversized goals, and long campaign names.
- Test reduced-motion settings and normal-text contrast to WCAG AA targets.
- Run Ruff, strict mypy, pytest, shipped JavaScript syntax, and canonical
  containerized health verification on the exact branch head.
- Before consumer release, obtain human acceptance and authorized live Instagram/model
  evidence. A green CI gate alone does not prove real-world provider functionality.
- No distribution or consumer release packaging should be triggered solely by this change.

## 11. Readability and interaction density

- Check 375px and desktop approval cards with long AI reasons, publication captions, and
  provider failures. The proposed text, confidence, approval, and schedule must be legible
  without opening technical diagnostics or scrolling sideways.
- Job IDs, decision IDs, retry attempt counts, idempotency keys and provider payload details
  must remain available through a keyboard-operable Technical details disclosure, not
  dominate the everyday decision surface.
- Failed or retrying jobs must show the last execution error visibly and truthfully, while
  the full error remains inspectable in technical details.
- Verify the review and execute paths remain explicit confirmations and do not bypass
  the canonical policy. An Execute button must be visually distinguishable as a write risk.
- The Evidence Library should show Edit and Mark reviewed without expanding details;
  Reject, Reset review and Delete remain available under More options, with native keyboard
  and Escape handling. Destructive actions still require their original confirmation.
- Use computed CSS in real Chromium to check essential 12px+ metadata, 14px+ action copy,
  16px+ card headings and no page-level horizontal overflow.
- Automated font-size checks are not an accessibility certification. Before release, conduct
  human screen-reader, contrast, readability, 200% zoom and real-device touch evaluation.

## Authority boundaries

`InstabotApplication` remains the application service; `CampaignRuntime` owns
planning/execution; `CampaignStore` owns atomic campaign updates; the SQLite
open-job/lease gates and optimistic `updated_at` version check are authoritative.
The browser is a client of these rules and cannot approve or execute a write by itself.
