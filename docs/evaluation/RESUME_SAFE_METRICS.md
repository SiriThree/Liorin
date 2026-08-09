# Resume-safe Metrics

This file is the only approved source for formal resume quality metrics.

## SAFE_TO_USE QUALITY METRICS

**NONE**

## NOT_SAFE_TO_USE / BLOCKED

- End-to-End Task Success: **NOT_SAFE_TO_USE** — metric not actually run; run validity=DEPENDENCY_BLOCKED; non-mock Production execution not verified; required real Judge not verified; missing run_id
- Required Gold Evidence Recall: **NOT_SAFE_TO_USE** — metric not actually run; run validity=DEPENDENCY_BLOCKED; non-mock Production execution not verified; missing run_id
- Grounded Claim Rate: **NOT_SAFE_TO_USE** — metric not actually run; run validity=DEPENDENCY_BLOCKED; non-mock Production execution not verified; required real Judge not verified; missing run_id
- First-pass Failure Recovery Rate: **NOT_SAFE_TO_USE** — metric not actually run; run validity=DEPENDENCY_BLOCKED; non-mock Production execution not verified; required real Judge not verified; missing run_id
- Safety Pass Rate: **NOT_SAFE_TO_USE** — metric not actually run; run validity=DEPENDENCY_BLOCKED; non-mock Production execution not verified; required real Judge not verified; missing run_id
- Context Token Reduction vs Full History: **NOT_SAFE_TO_USE** — metric not actually run; run validity=DEPENDENCY_BLOCKED; non-mock Production execution not verified; required real Judge not verified; missing run_id

## ENGINEERING_ONLY

- Full repository regression: 377 tests passed / 2 external-runtime integration skips
- Evaluation regression: 163 tests passed / 2 external-runtime integration skips
- Canonical legacy cases: 39
- Canonical validation cases: 5
- Safety formal candidates: 3
- Ablation configurations: 11
- Compileall: PASS

## Legacy metrics — DO NOT USE AS FORMAL QUALITY

- legacy_macro_objective_score: diagnostic only — DO_NOT_USE_AS_FORMAL_QUALITY_METRIC
- fact_coverage_proxy: lexical proxy only — DO_NOT_USE_AS_FORMAL_QUALITY_METRIC
- historical_context_token_reduction: 95.2% legacy component diagnostic — DO_NOT_USE_AS_FORMAL_QUALITY_METRIC
