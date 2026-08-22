# Liorin Memory V2 Architecture

Memory V2 makes memory task-scoped by default, keeps long-term memory user-scoped
only when a fact is durable, and treats context compaction as an ephemeral
runtime optimization instead of a new source of truth.

## Core Boundaries

1. Working Memory owns the current task state.
   - `WorkingMemory` now has `schema_version`, `active_task_id`, and `tasks`.
   - `TaskMemory` contains task goal, intent, status, legacy lists, and structured facts.
   - `ScopedMemoryFact` records key, value, scope, authority, confidence, status, and supersession.

2. Long-Term Memory owns durable user facts only.
   - LTM facts have an explicit `scope`.
   - `MemoryFactPolicy` rejects task-local keys such as `product_model`, `region`,
     `document_id`, and `policy_id`.
   - Durable user facts use keys such as `owned_product`, `preferred_language`,
     `timezone`, and communication/accessibility preferences.

3. Context assembly owns runtime selection.
   - `ContextItem` carries a `retention_policy`: `MUST_KEEP`,
     `KEEP_WHILE_ACTIVE`, `REHYDRATABLE`, `COMPACTABLE`, or `DROPPABLE`.
   - Active working memory and unresolved slots are protected.
   - Evidence and artifact references are rehydratable references, not compressed
     narrative facts.

4. Compaction is hybrid but bounded.
   - `HybridSemanticContextCompressor` may call a semantic summarizer only for
     compactable narrative history.
   - Working memory, identity, verified evidence, and artifact payloads stay
     outside the semantic compaction boundary.
   - Invalid semantic output or runtime failure falls back to deterministic
     `ContextCompressor`.

## Task Lifecycle

The working-memory extractor resolves each update into one of three paths:

- Same task: new slots are added to the active task.
- Correction: an explicit correction marker keeps the same task and supersedes
  stale structured facts.
- Task switch: explicit switch markers, or changed entity plus changed intent,
  suspend the previous task and create a new active task.

The legacy flat fields remain as a compatibility surface, but the authoritative
V2 state is the active task plus its active structured facts.

## Context Lifecycle

Retention policy is deterministic:

- Identity, current user message, and trusted system state are `MUST_KEEP`.
- Active working memory, unresolved slots, and current workflow state are
  `KEEP_WHILE_ACTIVE`.
- Artifact and evidence references are `REHYDRATABLE`.
- Old user/assistant turns are `COMPACTABLE`.
- Low-value items may be `DROPPABLE`.

Budgeting and selection now rank by retention policy before normal priority, so
active state is preserved before narrative history.

