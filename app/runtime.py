"""Shared logger and a cancellable sleep for long-running jobs."""

import logging
import threading

log = logging.getLogger("applybot")

_cancel = threading.Event()


class Cancelled(Exception):
    """Raised inside a run when the user cancels it."""


def sleep(seconds):
    """time.sleep that stops early (raising Cancelled) when the run is cancelled."""
    if _cancel.wait(max(0, seconds)):
        raise Cancelled()


def check_cancelled():
    if _cancel.is_set():
        raise Cancelled()


def request_cancel():
    _cancel.set()


def clear_cancel():
    _cancel.clear()
