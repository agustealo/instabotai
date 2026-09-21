# InstabotAI Intelligence Architecture

InstabotAI treats AI as a bounded decision subsystem, not as a string generator with direct authority over user accounts.

## Design goals

The intelligence layer is engineered to remain useful beyond Instagram-specific automation. The core contracts model objectives, evidence, candidate actions, critique, uncertainty, outcomes, and model-provider metadata. Instagram is an adapter that converts a selected candidate into a `PlannedAction`; policy and execution remain separate authorities.

The system is designed around seven requirements:

1. **Real model inference.** Decisions are produced by a configured language model through either the local Ollama adapter or an OpenAI-compatible model server.
2. **Evidence grounding.** Model candidates cite typed evidence IDs. Missing, invalid, or low-confidence evidence lowers deterministic support scores.
3. **Independent critique.** A second model pass audits the leading candidate for unsupported claims, ambiguity, missing evidence, and excessive risk. The critic can force abstention.
4. **Deterministic adjudication.** The model does not decide whether its own answer is safe enough. Utility, confidence, evidence support, learned reward, risk, and critic scores are combined outside the model and compared to a configured decision threshold.
5. **Durable outcome learning.** `ExperienceStore` records real outcomes and computes relevance-weighted priors for future decisions. This gives the system a feedback loop without allowing historical data to bypass current evidence or policy.
6. **Fail-closed execution.** Invalid JSON, schema violations, provider errors, context overflow, unsupported actions, critic objections, and low decision scores produce abstention rather than execution.
7. **Policy sovereignty.** The AI cannot disable approval requirements, daily limits, idempotency, provider capability checks, security controls, or the canonical `AutomationService` write path.

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

### OpenAI-compatible servers

`INSTABOTAI_AI_PROVIDER=openai_compatible` targets servers exposing a chat-completions compatible HTTP API. The base URL, model identifier, and optional API key are configured independently. This keeps the intelligence architecture portable across hosted and self-hosted deployments.

Provider output is never trusted directly. Both adapters normalize responses into the same `ModelReply` contract before the reasoning engine parses and validates JSON.

## Intelligence contracts

`EvidenceItem` contains a stable evidence ID, source, content, confidence, and observation time.

`DecisionCandidate` contains the proposed action, rationale, expected utility, model confidence, risk estimate, payload, target, and evidence references.

`ModelDecision` is the validated planner output and may contain zero candidates when action is not justified.

`DecisionReview` is the independent critic result. It includes support, risk, abstention, missing evidence, and objections.

`IntelligenceDecision` is the final auditable result after model generation and deterministic adjudication. It records abstention, selected candidate, reviewed score, uncertainty, provider, and model identity.

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

## Context discipline

The AI request has a hard configured character boundary. Evidence is ranked by confidence and safely reduced as complete JSON records when needed. The engine never truncates JSON mid-object. If a valid bounded request still cannot be produced, the decision fails closed.

This boundary exists for predictable cost, latency, prompt-injection surface, and model-context control.

## Security and authority boundaries

Model-generated actions are limited to the caller-supplied action vocabulary. For Instagram planning, that vocabulary is generated from the application `ActionType` enum rather than from model text.

A selected Instagram candidate becomes a `PlannedAction` with `ApprovalState.PENDING`. AI planning therefore cannot silently authorize its own write.

Credentials are handled only by provider adapters and runtime settings. They are not included in model prompts or outcome memory.

The generic research crawler remains separate from Instagram account access. Platform account operations continue through explicit provider adapters.

## Operator surface

`instabotai doctor` reports the configured AI provider, model, endpoint, critic state, decision threshold, and whether an API key is configured without printing the secret.

`instabotai plan <objective> --evidence-file evidence.json` invokes the real configured model, performs planner and critic passes, applies deterministic adjudication, and prints both the auditable `IntelligenceDecision` and the resulting pending `PlannedAction` when one is justified. It does not execute the action.

An optional `--context-file` accepts a bounded JSON object for account, campaign, or product context.

## Campaign integration

The campaign and scheduler layer should consume `IntelligenceEngine` rather than implement a second reasoning path. Its responsibility is to gather current campaign state, research evidence, account observations, resource constraints, and recent outcomes, then ask the intelligence engine for a decision. The scheduler may queue only the resulting pending action and must preserve the approval/policy boundary before execution.

This keeps one canonical intelligence system and one canonical write system as the product expands beyond the initial Instagram workflow.
