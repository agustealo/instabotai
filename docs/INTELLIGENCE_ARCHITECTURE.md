# InstabotAI Intelligence Architecture

InstabotAI treats AI as a bounded decision subsystem, not as a string generator with direct authority over user accounts.

## Design goals

The intelligence layer is engineered to remain useful beyond Instagram-specific automation. The core contracts model objectives, evidence, candidate actions, critique, uncertainty, outcomes, and model-provider metadata. Instagram is an adapter that converts a selected candidate into a `PlannedAction`; policy and execution remain separate authorities.

The system is designed around nine requirements:

1. **Real model inference.** Decisions are produced by a configured language model through either the local Ollama adapter or an OpenAI-compatible model server.
2. **Evidence grounding.** Model candidates cite typed evidence IDs. Missing, invalid, or low-confidence evidence lowers deterministic support scores.
3. **Independent critique.** A second model pass audits the leading candidate for unsupported claims, ambiguity, missing evidence, and excessive risk. The critic can force abstention.
4. **Deterministic adjudication.** The model does not decide whether its own answer is safe enough. Utility, confidence, evidence support, learned reward, risk, and critic scores are combined outside the model and compared to a configured decision threshold.
5. **Durable outcome learning.** `ExperienceStore` records real outcomes and computes relevance-weighted priors for future decisions. This gives the system a feedback loop without allowing historical data to bypass current evidence or policy.
6. **Durable decision audit.** Every production decision or abstention receives a stable `decision_id` and is persisted by `DecisionJournal` with its selected action, score, provider, model identity, explanation, critique, and timestamp.
7. **Fail-closed execution.** Invalid JSON, schema violations, provider errors, context overflow, unsupported actions, critic objections, and low decision scores produce abstention rather than execution.
8. **Prompt-injection containment.** Context, evidence, and candidate payloads are explicitly treated as untrusted data rather than instructions. Model output still passes typed validation, action-vocabulary containment, critique, and deterministic scoring.
9. **Policy sovereignty.** The AI cannot disable approval requirements, daily limits, idempotency, provider capability checks, security controls, or the canonical `AutomationService` write path.

## Verified runtime evidence

Documentation screenshots are restricted to real, currently implemented surfaces. The repository does not show speculative consumer dashboards while the consumer UI is still under development.

### Packaged runtime diagnostics

This is the actual `instabotai doctor` output captured from exact-head GitHub Actions run #104.

![InstabotAI runtime diagnostics](screenshots/runtime-doctor.svg)

### Exact-head quality gate

This is the successful release-evidence path for the same exact head.

![InstabotAI exact-head quality gate](screenshots/quality-gate.svg)

The screenshot provenance and operator-surface matrix are maintained in [PRODUCT_SURFACES.md](PRODUCT_SURFACES.md).

## Runtime flow

```text
objective
  -> bounded context
  -> typed evidence
  -> planner model
  -> schema validation
  -> allowed-action filter
  -> deterministic candidate scoring
  -> independent critic model
  -> deterministic reviewed score
  -> durable DecisionJournal entry
  -> abstain OR selected candidate
  -> Instagram adapter creates PENDING PlannedAction
  -> human/policy approval
  -> AutomationService
  -> provider
  -> durable outcome
  -> ExperienceStore feedback
```

## Model providers

### Ollama

`INSTABOTAI_AI_PROVIDER=ollama` is the default. It uses an actual local model server at `INSTABOTAI_AI_BASE_URL`, defaulting to `http://127.0.0.1:11434`. The default configured model is `llama3.2:3b`; operators may select a different installed model without changing application code.

The adapter uses Ollama's chat endpoint and sends the selected model, explicit system/user messages, non-streaming mode, and the configured temperature.

### OpenAI-compatible servers

`INSTABOTAI_AI_PROVIDER=openai_compatible` targets servers exposing a chat-completions compatible HTTP API. The base URL, model identifier, and optional API key are configured independently. This keeps the intelligence architecture portable across hosted and self-hosted deployments.

The adapter sends the selected model, system/user messages, configured temperature, and optional Bearer authorization to the configured chat-completions endpoint.

Provider output is never trusted directly. Both adapters normalize responses into the same `ModelReply` contract before the reasoning engine parses and validates JSON.

The test suite exercises the actual HTTP request/response contracts for both adapters with an in-process transport. It also proves that provider HTTP failures propagate instead of silently switching to fabricated or fallback AI output.

## Intelligence contracts

`EvidenceItem` contains a stable evidence ID, source, content, confidence, and observation time.

`DecisionCandidate` contains the proposed action, rationale, expected utility, model confidence, risk estimate, payload, target, and evidence references.

`ModelDecision` is the validated planner output and may contain zero candidates when action is not justified.

`DecisionReview` is the independent critic result. It includes support, risk, abstention, missing evidence, and objections.

`IntelligenceDecision` is the final auditable result after model generation and deterministic adjudication. It records a stable decision ID, abstention, selected candidate, reviewed score, uncertainty, provider, and model identity.

`IntelligenceProbe` is a validated live-model round-trip result containing provider, model, latency, and the model-confirmed reasoning capability.

## Scoring and learning

The deterministic candidate score combines:

- 30% expected utility
- 25% model confidence
- 20% cited-evidence support
- 15% relevance-weighted historical reward
- 10% inverse candidate risk

When critic review is enabled, the final score combines:

- 75% pre-critique score
- 15% critic support
- 10% inverse critic risk

The configured `INSTABOTAI_AI_MIN_DECISION_SCORE` is the final acceptance boundary. Critic abstention overrides the numerical score.

Historical reward is deliberately bounded. Prior outcomes can improve or weaken a candidate, but they cannot replace current evidence. Experience relevance is calculated against the current objective before it influences the score.

## Decision audit

`DecisionJournal` uses the same canonical SQLite state database while owning a separate `ai_decisions` table. Every production `IntelligenceEngine.reason()` result is persisted exactly once by stable decision ID, including abstentions.

The journal stores the complete validated `IntelligenceDecision` JSON plus indexed operational fields. It can retrieve one decision by ID or return a bounded newest-first audit feed. Duplicate decision IDs are rejected rather than overwritten.

The `instabotai decisions` CLI command exposes this audit feed without touching the execution system.

## Context discipline and prompt-injection containment

The AI request has a hard configured character boundary. Evidence is ranked by confidence and safely reduced as complete JSON records when needed. The engine never truncates JSON mid-object. If a valid bounded request still cannot be produced, the decision fails closed.

Planner and critic system instructions explicitly mark context, evidence, and candidate payloads as untrusted data, never instructions. That model-layer defense is intentionally not the only defense: all returned candidates still pass typed schema validation, allowed-action filtering, evidence-reference scoring, critic review, deterministic acceptance thresholds, and downstream policy.

This boundary exists for predictable cost, latency, prompt-injection surface, and model-context control.

## Security and authority boundaries

Model-generated actions are limited to the caller-supplied action vocabulary. For Instagram planning, that vocabulary is generated from the application `ActionType` enum rather than from model text.

A selected Instagram candidate becomes a `PlannedAction` with `ApprovalState.PENDING`. AI planning therefore cannot silently authorize its own write.

Credentials are handled only by provider adapters and runtime settings. They are not included in model prompts, the decision journal, or outcome memory.

The generic research crawler remains separate from Instagram account access. Platform account operations continue through explicit provider adapters.

## Operator surface

`instabotai doctor` reports the configured AI provider, model, endpoint, critic state, decision threshold, and whether an API key is configured without printing the secret. It is a configuration check, not proof that a model server is reachable.

`instabotai ai-check` performs a genuine inference request against the configured model. The model must return a validated structured capability response. Network, HTTP, parsing, or semantic probe failures fail the command rather than being replaced by a local fake response.

`instabotai plan <objective> --evidence-file evidence.json` invokes the real configured model, performs planner and critic passes, applies deterministic adjudication, journals the final decision, and prints both the auditable `IntelligenceDecision` and the resulting pending `PlannedAction` when one is justified. It does not execute the action.

`instabotai decisions --limit 25` displays recent journaled AI decisions and abstentions for operational inspection.

An optional `--context-file` accepts a bounded JSON object for account, campaign, or product context.

## Campaign integration

The campaign and scheduler layer should consume `IntelligenceEngine` rather than implement a second reasoning path. Its responsibility is to gather current campaign state, research evidence, account observations, resource constraints, and recent outcomes, then ask the intelligence engine for a decision. The scheduler may queue only the resulting pending action and must preserve the approval/policy boundary before execution.

The durable decision ID should be propagated into scheduled work and execution audit metadata so campaign outcomes can be traced back to the exact reasoning record that produced them.

This keeps one canonical intelligence system and one canonical write system as the product expands beyond the initial Instagram workflow.
