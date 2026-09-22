# Consumer-Trial Evidence Bundles

InstabotAI can export one typed, secret-free evidence bundle for a durable campaign job. The bundle is a review artifact, not an execution authority. It reads from the same canonical state, readiness, campaign, decision-journal, and action-ledger authorities already used by the product and does not approve, schedule, execute, retry, or alter a campaign job.

## What the bundle proves

A bundle ties one durable job to the surrounding consumer-trial state at export time:

- InstabotAI application version;
- deterministic SHA-256 fingerprint of the installed `instabotai` package payload;
- durable-state schema version, target, and integrity result;
- configured AI and Instagram provider identity without credentials;
- write-approval policy, confidence threshold, and bounded daily limits;
- static or live consumer-trial readiness;
- campaign snapshot;
- campaign-job lifecycle and explicit outcome state;
- the exact journaled AI decision referenced by the job;
- the action-ledger row for the job idempotency key when present;
- current daily usage counters;
- a SHA-256 content digest whose covered fields are defined by the bundle format version.

New exports use evidence format **2**, which covers the complete accepted evidence document including integrity metadata other than the digest itself. Archived format-1 bundles remain verifiable using the original format-1 digest contract, which excluded the integrity object. The verifier dispatches by the declared format version rather than silently reinterpreting old evidence under new rules.

The related durable campaign, job, decision, action-ledger, and usage projections are all read from one SQLite backup snapshot. That snapshot is created with SQLite's backup API before the evidence read begins, so those records represent one consistent database point in time rather than a mixture of separate live reads.

The package fingerprint identifies the installed code payload even when a wheel or container has no Git metadata. It is not a release signature.

## Export from the CLI

Export static readiness evidence:

```bash
instabotai trial-evidence JOB_ID --output ./trial-evidence.json
```

If `--output` is omitted, InstabotAI writes `trial-evidence-JOB_ID.json` in the current working directory.

Include genuine model and read-only Instagram connectivity checks in the embedded readiness result:

```bash
instabotai trial-evidence JOB_ID --live --output ./trial-evidence-live.json
```

Require the optional research capability in that readiness result:

```bash
instabotai trial-evidence JOB_ID --require-research
```

Evidence export does not treat a readiness failure as permission to execute or as a reason to hide the evidence. The readiness report is recorded as observed so an operator can review why a trial was or was not ready.

## Verify an exported bundle

```bash
instabotai trial-evidence-verify ./trial-evidence.json
```

Verification first performs strict typed loading. Unknown fields in the evidence envelope, runtime projection, readiness projection, readiness checks, or integrity metadata are rejected rather than silently discarded. The integrity contract currently accepts only `algorithm="sha256"` and `signed=false`, and only supported evidence format versions are accepted.

After strict loading, verification recomputes the canonical SHA-256 digest according to the declared format version. Format 1 retains its historical digest calculation for archived bundles. Format 2 binds the accepted integrity metadata into the digest. Exit code `0` means the accepted document matches its recorded digest. Exit code `2` means the typed file loaded successfully but its content no longer matches the recorded digest.

The digest is **tamper-evident, not signed**. SHA-256 detects content changes after export, but it does not prove which person or machine created the file. InstabotAI must not describe this field as a signature or authenticated provenance unless a real signing identity is added later.

## Consumer console

Each campaign job exposes **Export evidence**. The console requests:

```text
GET /api/campaign-jobs/{job_id}/evidence
```

and downloads the returned JSON in the browser. The endpoint is read-only and inherits the console's `Cache-Control: no-store` API policy. The server does not choose or write a client filesystem path for browser exports.

The HTTP endpoint also accepts:

```text
?live=true
?require_research=true
```

for operators who deliberately want those readiness modes.

## Secret handling

Evidence generation recursively sanitizes the exported campaign, job, decision, ledger, and usage projections before the digest is calculated.

The sanitizer removes or replaces:

- configured AI API keys;
- configured Instagram access tokens;
- private-provider passwords;
- configured proxy credentials;
- challenge and replacement-password values;
- values beneath credential-like keys after normalizing snake_case, kebab-case, camelCase, and PascalCase naming, including forms such as `token`, `access_token`, `accessToken`, `refreshToken`, `password`, `secret`, `api_key`, `apiKey`, `clientSecret`, `authorization`, `cookie`, `session`, and credential-related fields;
- bearer credentials embedded inside otherwise ordinary strings.

CLI file export is atomic. On platforms that support POSIX permissions, InstabotAI makes the temporary and final evidence files private with mode `0600` on a best-effort basis.

Secret redaction is defense in depth, not permission to put secrets into campaign evidence or action payloads. Runtime secrets should remain in environment variables or another operator-controlled secret store.

## Read-only authority boundary

The evidence path is deliberately downstream of product authority:

```text
StateSchema
  + ConsumerTrialReadinessService
  + one SQLite backup snapshot
      + CampaignStore
      + DecisionJournal
      + ActionLedger
          |
          v
  TrialEvidenceService
          |
          +--> typed JSON bundle
          +--> SHA-256 content digest
```

The snapshot does not create a second persistence authority. Existing canonical stores still interpret the state; the backup simply gives all evidence reads one stable database image.

There is no path from `TrialEvidenceService` back into approval, `AutomationPolicy`, quota reservation, provider execution, retry ownership, or business-outcome recording.

The application service, CLI, HTTP API, and browser download all use this same evidence authority. They do not maintain separate evidence schemas or secret filters.

## Interpretation

A bundle should be read as an observation of durable state at one moment. In particular:

- `provider_result` records what the configured provider path returned, not proof of business success;
- `outcome_reward` is present only when an explicit observed business outcome has been recorded;
- `readiness.ready=true` means the selected readiness profile has no required blockers, not that arbitrary writes are authorized;
- an absent action-ledger row can be legitimate for a job that has not entered the canonical write path yet;
- package fingerprint equality means the packaged InstabotAI file payloads hash identically, not that the surrounding OS or provider environment is identical.

The durable database projections come from one SQLite snapshot. Live readiness probes, when explicitly requested, are external observations performed after that durable snapshot and are labeled as such in the readiness report.

## Trial review sequence

For a supervised real-account trial:

1. install the exact candidate package or image;
2. run static and then live readiness as required by the trial plan;
3. create or plan evidence-grounded work;
4. review and explicitly approve the intended job;
5. execute only through the canonical campaign and automation path;
6. inspect provider and durable ledger state;
7. record the real business outcome only after it is observed;
8. export the job evidence bundle;
9. run `trial-evidence-verify` on the exported file;
10. retain the bundle according to the operator's trial-data retention policy.

If the bundle exposes a disagreement between readiness, job state, provider result, ledger state, and outcome, fix the owning product boundary. Do not create a second execution or audit path to make the report look green.

## CI authority

Repository CI must prove more than module importability. The release gate is expected to keep evidence covered by:

- typed unit and integration regressions;
- deliberate nested-secret contamination tests, including camelCase credential keys;
- strict-document and integrity-metadata tampering tests;
- archived format-1 verification compatibility and format-2 integrity binding;
- one-snapshot durable-read concurrency regression proof;
- digest-tampering tests;
- atomic export/load/verify tests;
- read-only HTTP boundary tests with `Cache-Control: no-store`;
- shipped browser-asset parsing tests;
- clean-wheel evidence generation and independent verification;
- production-container evidence generation and independent verification as the non-root runtime user.

Real authenticated provider probes remain separate from public repository CI because production credentials do not belong in repository build configuration.
