# Blind Test Protocol

`data/blind_test_inputs_v7_3.json` is the only blind-test artifact that may be
shared with benchmark runners.

The private blind-test gold artifact must be supplied only by a maintainer,
review owner, or CI secret. Do not commit it, print it, log it, or copy it into
local run directories.

Recommended flow:

1. Freeze code, model configuration, prompts, and dependency lock files.
2. Record the commit hash and runtime environment.
3. Generate predictions exactly once from the public blind-test inputs.
4. Let the gold custodian run scoring in a private environment.
5. Archive predictions, signed reports, request logs, and configuration hashes.
6. Use a new benchmark version for any later code or prompt change.
