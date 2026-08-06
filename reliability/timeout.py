"""Synchronous timeout wrapper for blocking external calls."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, TypeVar

T = TypeVar("T")


class OperationTimeoutError(TimeoutError):
    pass


def execute_with_timeout(operation: Callable[[], T], timeout_seconds: float) -> T:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="liorin-timeout")
    future = executor.submit(operation)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise OperationTimeoutError(f"operation exceeded {timeout_seconds}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
