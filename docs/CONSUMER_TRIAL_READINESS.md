# Consumer-Trial Readiness

InstabotAI exposes one canonical readiness authority for controlled consumer trials. The CLI and consumer console use the same `ConsumerTrialReadinessService`; neither surface maintains a separate checklist or optimistic configuration heuristic.

## Static readiness

Run:

```bash
instabotai trial-readiness
```

Static readiness performs no external AI or Instagram request. It verifies:

- the installed InstabotAI runtime and package entrypoint;
- SQLite integrity plus a transactional write probe against `INSTABOTAI_STATE_DB_PATH`;
- configured AI provider/model/base URL;
- complete credentials for the selected Instagram provider;
- optional Crawl4AI package availability;
- globally required human write approval for the consumer-trial phase;
- non-zero bounded daily write capacity;
- secret-free result serialization.

The command exits with code `0` when every required check passes and code `2` when one or more required blockers remain. Optional missing research support is a warning unless research is explicitly required.

To make research a required trial capability:

```bash
instabotai trial-readiness --require-research
```

## Live readiness

Run:

```bash
instabotai trial-readiness --live
```

Live readiness includes every static check and additionally performs:

1. a genuine structured round trip through the configured reasoning provider; and
2. a real read-only Instagram profile request through the selected provider.

The live readiness path never executes an Instagram write. It is intentionally read-only so an operator can prove account/model connectivity before approving any consumer-trial action.

Live failures report the failed boundary and exception class without echoing raw upstream exception text. This prevents provider errors from accidentally returning tokens, passwords, authorization headers, or other secret-bearing material in readiness output.

## Consumer console

The Overview workspace loads static readiness automatically through:

```text
GET /api/readiness
```

The **Run live checks** control uses:

```text
POST /api/readiness/probe
```

Both endpoints return the same typed `ConsumerTrialReadiness` contract used by the CLI. API responses are covered by the console's `Cache-Control: no-store` and browser security-header policy.

The readiness report uses four states:

| State | Meaning |
| --- | --- |
| `pass` | The check is satisfied. |
| `warn` | Optional capability is unavailable or needs attention but does not block the selected trial profile. |
| `fail` | A required consumer-trial condition is not satisfied. |
| `skip` | A live or optional check was not requested. |

`ready=true` means there are no required `fail` checks. It does not mean InstabotAI has permission to perform arbitrary actions. Write execution remains separately governed by campaign/job state, approval, `AutomationPolicy`, transactional quota reservation, idempotency, and the selected Instagram provider.

## Provider requirements

### Official provider

Static readiness requires both:

```bash
INSTABOTAI_INSTAGRAM_ACCOUNT_ID
INSTABOTAI_INSTAGRAM_ACCESS_TOKEN
```

Live readiness then verifies those credentials with a real read-only profile request.

### Private provider

Static readiness requires:

```bash
INSTABOTAI_PRIVATE_INSTAGRAM_USERNAME
INSTABOTAI_PRIVATE_INSTAGRAM_PASSWORD
```

and the optional `[private]` package extra containing `instagrapi`.

Live readiness uses the same configured private-provider session/account path as normal read operations. Platform challenges remain Instagram-controlled and are surfaced rather than bypassed.

## Research requirements

Research is optional for a base consumer trial. When enabled, install:

```bash
python -m pip install 'instabotai[research]'
```

or, from a source checkout:

```bash
python -m pip install -e '.[research]'
```

Use `--require-research` when the trial plan depends on Crawl4AI. The readiness engine then treats a missing research extra as a blocker instead of a warning.

## CI authority

The Quality Gate verifies readiness from three packaging paths:

1. editable development installation;
2. a freshly built wheel installed into a clean virtual environment; and
3. the production Docker image running as its non-root application user.

The wheel/container readiness smoke uses non-secret CI-only placeholder provider values and static readiness. It proves packaging, command registration, SQLite state creation, policy defaults, and the readiness contract without impersonating a successful authenticated Instagram or AI call.

Authenticated live-provider evidence is intentionally separate from repository CI because real credentials must not be embedded in public build configuration.

## Consumer-trial release sequence

Before a supervised real-account trial:

1. install the exact candidate package/image;
2. configure the intended AI and Instagram provider;
3. keep `INSTABOTAI_REQUIRE_WRITE_APPROVAL=true`;
4. enable only the daily action limits required for the trial;
5. run `instabotai trial-readiness`;
6. run `instabotai trial-readiness --live`;
7. inspect the same readiness report in the consumer console;
8. perform a reviewed AI plan with real evidence;
9. approve only the intended durable campaign job;
10. execute through the canonical write path;
11. verify the provider result and ledger state;
12. record business outcome only after the real-world result is observed.

A failed readiness check should be corrected at its owning boundary. It must not be bypassed by adding another provider, scheduler, agent, or UI-specific execution path.
