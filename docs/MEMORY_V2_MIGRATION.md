# Memory V2 Migration Notes

Memory V2 is an additive migration. Existing checkpoints remain readable.

## Read Path

`WorkingMemory.from_state()` accepts V1-style flat state. When no task list is
present, it constructs one active `TaskMemory` from the legacy fields:

- `task_goal`
- `current_intent`
- `confirmed_facts`
- `open_questions`
- `constraints`
- `decisions`
- `failed_attempts`
- `next_actions`

Legacy fact strings such as `product_model=X100` are converted into low-trust
`ScopedMemoryFact` records with `authority=LEGACY_CHECKPOINT` and task scope.

## Write Path

New writes emit both:

- compatibility flat fields, for older callers and prompt rendering;
- V2 fields, including `schema_version`, `active_task_id`, and `tasks`.

This allows old states to resume without a one-time database migration.

## Long-Term Memory Policy Change

Task-local facts are no longer promoted into LTM. In particular, current
`product_model`, `region`, document/policy IDs, and similar per-task slots are
rejected by policy.

For cross-session durable user profile memory, use user-scoped keys such as:

- `owned_product`
- `preferred_language`
- `timezone`
- `communication_preference`
- `accessibility_preference`

## Rollback

Rollback is straightforward because legacy flat fields are still written.
Reverting V2 code leaves old consumers able to read `confirmed_facts`,
`open_questions`, and related fields. V2-specific `tasks` metadata would simply
be ignored by older readers.

