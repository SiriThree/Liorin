"""Cross-suite test isolation for process-global observability registries.

Production intentionally exposes a process-global MemoryMetricsRegistry.  Pytest
modules should not, however, inherit counters emitted by a previous test when
asserting per-test deltas.  Resetting the registry at test boundaries changes no
production runtime behavior and makes combined-suite execution deterministic.
"""
from __future__ import annotations

import pytest

from metrics import reset_default_memory_metrics


@pytest.fixture(autouse=True)
def _isolate_default_memory_metrics():
    reset_default_memory_metrics()
    yield
    reset_default_memory_metrics()
