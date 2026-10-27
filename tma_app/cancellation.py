"""Cooperative cancellation without importing any GUI objects."""
from concurrent.futures import CancelledError


def check_cancelled(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise CancelledError()
