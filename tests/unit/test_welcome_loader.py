"""Unit tests for the welcome screen's request tracking."""

import itertools

import pytest

from jparty.ui.welcome_loader import LatestRequest

pytestmark = pytest.mark.unit


def test_latest_request_only_the_newest_id_is_current() -> None:
    """Starting a new request makes the older one stale."""
    request = LatestRequest()

    first = request.begin()
    second = request.begin()

    assert request.is_current(second)
    assert not request.is_current(first)


def test_latest_request_cancel_makes_every_request_stale() -> None:
    """Cancel drops the request in flight without starting a new one."""
    request = LatestRequest()
    started = request.begin()

    request.cancel()

    assert not request.is_current(started)


def test_latest_requests_sharing_ids_never_match_each_other() -> None:
    """A request for a rebuilt target can't match one for its replacement."""
    ids = itertools.count(1)
    old_target = LatestRequest(ids)
    stale = old_target.begin()

    new_target = LatestRequest(ids)
    fresh = new_target.begin()

    assert fresh != stale
    assert not new_target.is_current(stale)
