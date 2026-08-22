# Memory V2 Architecture Audit

This audit is based on the current repository code and the existing Phase 1-7
memory/context documents. It records the real baseline before the Memory V2
incremental refactor.

## Working Memory

Current model: `memory/working/models.py::WorkingMemory` is a single
checkpoint-local task snapshot with:

- `session_id`
- `task_goal`
- `current_intent`
- `confirmed_facts`
- `open_questions`
- `constraints`
- `decisions`
- `failed_attempts`
- `next_actions`
- `last_updated`

It is JSON-safe and recovered through `WorkingMemory.from_state()`. Updates are
deterministic: `WorkingMemoryExtractor` reads structured workflow/query state,
then `MemoryDeltaDetector` suppresses no-op writes.

Current gaps:

- The model is flat and session-scoped; it has no explicit `active_task_id` or
  task list.
- `confirmed_facts` is still a tuple of strings. A corrected value can coexist
  with an older value such as `product_model=X100` and `product_model=X200`.
- There is no fact-level lifecycle for task-local entities. Correction,
  supersession, invalidation, and task switch semantics are not first-class.
- New tasks are inferred only through caller-provided workflow state; there is
  no deterministic task boundary resolver that uses QueryUnderstanding entities.
- WorkingMemory can still carry task-local business entities that should not be
  interpreted as durable long-term facts.

## Long-term Memory

Current candidate sources: `memory/facts/extractor.py::MemoryCandidateExtractor`
reads explicit `memory_fact_candidates`, `user_confirmed_facts`,
`business_system_facts`, workflow `stable_facts`, legacy working-memory strings,
and narrow current-message confirmations.

Policy: `MemoryFactPolicy` checks owner identity, anonymous user, stability,
future reuse, source trust, confidence, verification, expiry, and value size.
Governance wraps it with sensitive-content and prompt-injection filtering.

Current gaps:

- The default stable/future-reuse key set still includes task-local fields such
  as `product_model`, `product_name`, `device_model`, `region`, and
  `product_version`.
- Legacy working-memory values can be represented as candidates, although the
  policy currently rejects them unless explicitly marked stable/reusable.
- The schema does not yet distinguish `current_product` from durable
  `owned_product` in the promotion boundary.
- `MemoryFactCandidate` does not carry a formal `scope` field; scope is implied
  through metadata and policy.
- Conflict/correction exists through governance update paths, but multi-value
  active/superseded semantics are still limited by one deterministic fact id per
  owner/key.

## Context Engineering

Current item model: `context_engine/models.py::ContextItem` includes:

- `id`
- `type`
- `content`
- `source`
- `priority`
- `timestamp`
- `token_cost`
- `metadata`

`required` is a compatibility property derived from `metadata["required"]`.
Selection and budget still primarily use `required` and numeric `priority`.

Compaction exists in `context_engine/compaction/`. The current deterministic
compressor only handles historical narrative/tool-reference items and validates
working-memory and identity preservation. It is model-call scoped and does not
write summary state back into business memory.

Current gaps:

- There is no explicit `ContextRetentionPolicy`; the system still uses
  `required` plus static priority as the dominant retention signal.
- Trigger metadata reports token and item counts, but not full composition-aware
  pressure such as protected active tokens, rehydratable tokens, narrative
  tokens, and noise tokens.
- Validation preserves flat WorkingMemory renderings but does not fingerprint
  active task structured state.
- There is no semantic narrative compactor adapter; deterministic compaction is
  the only implementation.

## Artifact Memory

Tool results and retrieval evidence are converted to Artifact references by
`context_engine/builder.py` using `ArtifactRegistry`. Full payloads remain in the
store and are resolved through `ArtifactResolver` with exact `IdentityContext`
matching.

Current strengths:

- Context gets references, not full payload.
- Artifact access is identity-bound.
- Deleted/unavailable artifacts do not silently resolve.

Current gaps:

- Default store is still process-local unless production bootstrap installs a
  backend.
- Resolver failure states are represented by exceptions/lifecycle records, but
  not every caller has a user-visible unavailable artifact surface.

## Governance

Identity is centralized through `IdentityContext` and `IdentityResolver`.
Long-term memory access uses tenant/user ownership checks. Artifact access is
stricter and requires exact identity context.

Current gaps:

- `IdentityContext` is an ownership contract, not authentication.
- Task-local memory lifecycle events are not yet scope-aware at the fact level.
- Enterprise audit remains process-local unless production infrastructure is
  bootstrapped.

## Evaluation

Existing coverage includes:

- working-memory runtime and benchmark tests;
- memory delta/no-op tests;
- context runtime/compaction tests;
- artifact runtime/benchmark tests;
- long-term memory runtime tests;
- governance and memory isolation benchmarks;
- context/memory evaluation contracts in `tests/evaluation`.

Missing or partial coverage:

- task switch with explicit active/inactive task lifecycle;
- same-task entity correction with supersession;
- stale task entity leakage from old working memory into current context;
- resume previous task;
- active task state fingerprint preservation through compaction;
- incorrect long-term promotion of task-local entities;
- semantic compactor failure fallback.

## Minimal V2 Direction

The least disruptive path is:

1. Extend WorkingMemory with `schema_version`, `active_task_id`, `tasks`, and
   structured task facts while keeping legacy flat fields readable.
2. Add deterministic task boundary resolution and task-local supersession in the
   WorkingMemory extractor.
3. Add `ContextRetentionPolicy` while preserving the `required` property.
4. Make compaction pressure composition-aware and validate active task
   structured-state fingerprints.
5. Add explicit LTM candidate scope and default-deny task-local promotion keys.
6. Keep Artifact as reference/rehydration, not payload-in-context.
