"""Stopping a `validate_skin` run from another thread (kdk-only)."""

import threading
from pathlib import Path

import pytest

from kdk.core import Cancelled, validate_skin

SKIN = Path(__file__).resolve().parent / "fixtures" / "clean_skin"


def test_cancel_stops_the_run_at_its_next_progress_report():
    """Setting the event during a step raises Cancelled before any later step reports."""
    cancel = threading.Event()
    steps = []

    def report(step, _total, _message):
        steps.append(step)
        if step == 2:
            cancel.set()

    with pytest.raises(Cancelled):
        validate_skin(str(SKIN), isolated=True, progress_callback=report, cancel=cancel)
    assert max(steps) == 2


def test_an_event_nobody_sets_lets_the_run_finish():
    """An unset event changes nothing; the run returns its issues."""
    result = validate_skin(str(SKIN), isolated=True, cancel=threading.Event())
    assert not result.get("error")
    assert "issues" in result
