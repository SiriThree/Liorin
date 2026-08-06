# Phase 2 Working Memory — Pre-Phase 3 Risk Register

> Phase 5 状态更新：风险 1 已由 Phase 3.0 IdentityContext 完成基础修复；风险 2 已由 Phase 3.1 Memory Delta、semantic fingerprint、No-op Detection 和 lifecycle attributes 完成；风险 3 已由 Phase 5 `MemoryFact` 的 source、confidence、verified 与保守 legacy migration 完成基础修复。身份认证、ACL、durable Store、冲突治理和真实模型 Memory 质量评测仍属于后续阶段。

## 1. Purpose and scope

This document records three architectural risks identified after Phase 2 and tracks their implementation status. IdentityContext was implemented in Phase 3.0, Memory Delta in Phase 3.1, and fact-level provenance/confidence in the Phase 5 MemoryFact foundation. Durable governance, authentication, ACL, conflict handling and production quality evaluation remain follow-up gates.

The original Phase 2 runtime was:

```text
Structured workflow state
  → WorkingMemoryExtractor
  → Candidate
  → Policy
  → In-memory lifecycle adapter
  → LangGraph checkpoint state
  → Context Runtime injection
```

Phase 3.0 and 3.1 incrementally add IdentityContext and Memory Delta before persistence. No Memory Store, Conversation Memory, Long-term Memory, Artifact Memory, permission system, identity registry, or event bus has been added.

---

## 2. Risk 1 — Runtime identity and checkpoint identity are not unified

### 2.1 Current condition after Phase 3.0

Phase 3.0 introduced a canonical checkpoint-safe `IdentityContext` and `IdentityResolver` for tenant, user, conversation, LangGraph thread, and runtime session identifiers. Working Memory and lifecycle records now carry this identity snapshot.

Authentication, ACL enforcement, delete/audit APIs and Artifact/sub-Agent propagation remain incomplete, so the foundation is not yet a complete enterprise Memory Governance implementation.

### 2.2 Why this matters

Without a canonical identity boundary, future components may:

- read or inject memory from the wrong tenant or user;
- create multiple Working Memory records for one conversation;
- bind a restarted session to the wrong LangGraph thread;
- fail to delete all memory belonging to a user or conversation;
- produce audit events that cannot be traced back to the checkpoint that used them;
- evaluate memory recall against the wrong subject or conversation.

### 2.3 Implemented foundation and remaining governance

The implemented checkpoint-safe identity model is:

```python
IdentityContext(
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    thread_id: str,
    session_id: str,
)
```

Identifier semantics must be explicit:

- `tenant_id`: authorization and data-isolation boundary;
- `user_id`: authenticated memory subject;
- `conversation_id`: durable business conversation identity;
- `thread_id`: LangGraph checkpoint stream identity;
- `session_id`: one runtime interaction/session identity.

“Unified” does not require all values to be equal. It requires one canonical `IdentityContext`, deterministic mapping rules, and validation before Memory read/write/injection.

### 2.4 Acceptance status

Phase 3.0 demonstrates items 1–3 below; items 4–5 remain governance work:

1. `IdentityContext` round-trips through checkpoint state;
2. `thread_id` and `session_id` mismatch is detected rather than silently accepted;
3. every lifecycle record can carry tenant/user/conversation/thread/session correlation;
4. Context injection rejects identity-mismatched Memory;
5. delete/audit APIs can select memory by tenant, user, conversation, or thread.

### 2.5 Implementation reference

The core contract is implemented in `identity/` and documented in `docs/PHASE3_0_IDENTITY_CONTEXT.md`. ACL, deletion, retention, audit selection and Artifact/sub-Agent enforcement remain future governance work.

---

## 3. Risk 2 — Working Memory updates can create lifecycle event noise

### 3.1 Current condition after Phase 3.1

The workflow still invokes `WorkingMemoryUpdater` from selected state-changing nodes, but the updater now computes a semantic SHA-256 fingerprint and `MemoryUpdate` before policy/persistence. A semantically unchanged candidate returns the previous WorkingMemory, skips Policy and Persist, and emits no lifecycle record.

The 120-record cap remains a storage safety bound. It is no longer the primary deduplication mechanism. Real Candidate/Policy/Persist records carry changed fields, reason, old/new fingerprints, additions and removals.

### 3.2 Why this matters

Uncontrolled update frequency can cause:

- lifecycle logs dominated by no-op changes;
- unnecessary checkpoint writes;
- noisy governance/audit trails;
- misleading memory update metrics;
- repeated downstream indexing or persistence once a durable store exists;
- loss of meaningful older audit records because the cap is consumed by duplicates.

### 3.3 Implemented contract

Add a structured delta between extraction and policy/persistence:

```python
MemoryUpdate(
    changed_fields: tuple[str, ...],
    reason: str,
    previous_fingerprint: str,
    candidate_fingerprint: str,
    additions: Mapping[str, object],
    removals: Mapping[str, object],
)
```

The precise representation may differ, but it must provide:

- deterministic semantic comparison;
- changed-field attribution;
- a human/audit-readable reason;
- no-op detection;
- stable fingerprints for idempotency and replay;
- distinction between additions, removals, and replacements.

Implemented flow:

```text
Structured state
  → WorkingMemory candidate
  → Memory Delta
  → no-op? stop
  → Policy decision
  → Persist/update
  → lifecycle record with changed_fields
```

### 3.4 Event emission rule

A state callback must not automatically imply a Memory update. At minimum:

- no semantic change → no `UPDATED` persistence event;
- rejected candidate → policy record only when rejection is operationally meaningful;
- accepted change → one update transaction correlated to its Candidate/Policy/Persist records;
- repeated replay with the same fingerprint → idempotent outcome.

### 3.5 Acceptance result

Phase 3.1 demonstrates:

1. no-op updates produce no persisted `UPDATED` event;
2. every accepted update reports `changed_fields`;
3. repeated processing of the same state is idempotent;
4. lifecycle volume is measured as meaningful updates per turn, not raw hook calls;
5. the record cap remains a safety bound, not the primary deduplication mechanism.

### 3.6 Implementation reference

Implemented in `memory/delta/` and integrated through `memory/working/updater.py` and `agents/support_workflow.py`. See `docs/PHASE3_1_MEMORY_DELTA.md`. Durable stores and external audit sinks remain out of scope.

---

## 4. Risk 3 — Confirmed facts have no fact-level provenance or confidence

### 4.1 Current condition

`WorkingMemory.confirmed_facts` currently stores compact string values. Lifecycle `MemoryMetadata.confidence` describes the memory record as a whole and is currently emitted as `1.0`; it does not represent confidence for each fact.

The runtime therefore cannot distinguish:

- a value explicitly confirmed by the user;
- a value read from a verified system of record;
- an Agent inference;
- an unverified extraction;
- a stale fact that was once correct.

### 4.2 Why this matters

Treating every fact as equally reliable can cause:

- inferred facts to be presented as user-confirmed facts;
- unsafe promotion from Working Memory to Long-term Memory;
- incorrect policy decisions;
- inability to re-ask for low-confidence information;
- misleading evaluation of memory precision and pollution.

### 4.3 Required future contract

Before Long-term Memory promotion, introduce a fact-level model similar to:

```python
MemoryFact(
    value: object,
    source: str,
    confidence: float,
    verified: bool,
)
```

For governance and conflict resolution, the final model should also consider stable identity and time fields such as:

```text
fact_id
key
observed_at
verified_at
verified_by
source_reference
```

Suggested confidence policy:

- explicit user confirmation: high confidence, but still subject to identity and freshness rules;
- verified system-of-record value: high confidence with source reference;
- deterministic workflow extraction: confidence derived from field/source contract;
- Agent inference: lower confidence and `verified=false`;
- conflicting facts: retain provenance and require resolution instead of overwriting silently.

Confidence is not truth probability by itself. It must be interpreted together with source, verification status, freshness, and policy.

### 4.4 Compatibility requirement

Changing `confirmed_facts` from strings to structured facts is a checkpoint-schema change. Migration must be explicit:

- old string facts remain readable;
- old facts are assigned conservative provenance such as `source="legacy_checkpoint"`;
- schema version is recorded;
- rollback does not make new checkpoints unreadable by the previous runtime without warning.

### 4.5 Acceptance gate

Before any Working Memory fact is promoted to Long-term Memory:

1. each promoted fact has source, confidence, and verification state;
2. inferred facts cannot masquerade as user-confirmed facts;
3. conflicts are represented and policy-resolved;
4. legacy checkpoints are migrated deterministically;
5. evaluation reports precision by fact source/confidence class.

### 4.6 Recommended phase

Design the compatibility contract before Phase 3 finalization. Implement and enforce fact-level confidence before the Long-term Memory phase.

---

## 5. Cross-phase decision

These risks are now release-planning gates:

| Risk | Current status | Earliest implementation | Must be complete before |
|---|---|---|---|
| IdentityContext | Phase 3.0 foundation implemented; Artifact propagation completed in Phase 4 | Phase 3.0 | authentication and ACL still pending |
| Memory Delta | Phase 3.1 implemented | Phase 3.1 | durable persistence can now consume semantic updates |
| MemoryFact confidence | Implemented in Phase 5 foundation | Phase 5 | Long-term Memory promotion |

Phase 2 remains complete for checkpoint-local Working Memory. Phase 5 adds the first policy-gated long-term Fact runtime, but it must not be described as enterprise-governed durable Memory until authentication, ACL, durable persistence, user correction/deletion and production evaluation gates are satisfied.

## 6. Files changed by this risk record

```text
docs/PHASE2_WORKING_MEMORY_RISKS.md
docs/PHASE2_WORKING_MEMORY.md
CHANGELOG.md
```

No Python source, tests, runtime configuration, or checkpoint schema is changed.

## 7. Validation and rollback

Validation for this documentation-only hardening:

- confirmed the three risks against the current Phase 2 models and updater;
- confirmed no Python source file was modified;
- no pytest result is claimed because runtime behavior did not change.

Rollback: remove this file and the references added to the Phase 2 document and changelog. No state or data migration is involved.
