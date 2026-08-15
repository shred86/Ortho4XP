"""Tests for Overpass server selection in ``src/O4_OSM_Utils.py``.

Covers the robustness fixes made after the PR #93 review:

* the accumulating per-request failure exclusion (no server is retried
  while an untried one remains, the round resetting once all failed),
* stickiness being dropped by a failure so a LATER request does not
  start on a server whose previous request just died,
* a short rate-limit penalty being sat out on the SAME server,
* the two patience tiers (quick first attempts, full window later),
* the second /api/status probe round that rescues transiently silent
  servers.

All headless: HTTP posting, status probing, and back-off sleeping are
monkeypatched; no network access.
"""

import pytest

import O4_OSM_Utils as OSM


class _FakeResponse:
    """Minimal stand-in for the pieces of requests.Response that
    _describe_overpass_response_problem and the 429 branch read."""

    def __init__(self, status_code=200, content=b"<osm></osm>", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


def _good_response():
    return _FakeResponse()


def _rate_limited_response(retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return _FakeResponse(
        status_code=429, content=b"rate limited", headers=headers
    )


@pytest.fixture()
def three_servers(monkeypatch):
    """Install a synthetic three-server pool and neutralise stickiness.

    ``last_successful_server_key`` is function-level state that outlives
    a single request, so it must be cleared between tests."""
    monkeypatch.setattr(
        OSM,
        "overpass_servers",
        {
            "alpha": "https://alpha.example/api/interpreter",
            "beta": "https://beta.example/api/interpreter",
            "gamma": "https://gamma.example/api/interpreter",
        },
    )
    monkeypatch.setattr(OSM, "overpass_server_choice", "random")
    if hasattr(OSM.get_overpass_data, "last_successful_server_key"):
        monkeypatch.delattr(
            OSM.get_overpass_data, "last_successful_server_key"
        )
    return ["alpha", "beta", "gamma"]


@pytest.fixture()
def captured_sleeps(monkeypatch):
    """Collect the back-off sleeps instead of serving them."""
    slept = []
    monkeypatch.setattr(OSM.time, "sleep", lambda seconds: slept.append(seconds))
    return slept


def _stub_probe_to_first_candidate(monkeypatch, probed_candidate_lists):
    """Record each candidate list the status probe sees; pick its head."""

    def fake_probe(candidate_keys):
        candidate_keys = list(candidate_keys)
        probed_candidate_lists.append(candidate_keys)
        return candidate_keys[0]

    monkeypatch.setattr(OSM, "_select_most_available_server_key", fake_probe)


def _record_selection_inputs(monkeypatch):
    """Wrap the selector so each attempt's exclusion set is observable."""
    recorded_failed_sets = []
    real_select = OSM._select_overpass_server_key

    def recording_select(server_keys, failed_server_keys=frozenset()):
        recorded_failed_sets.append(set(failed_server_keys))
        return real_select(server_keys, failed_server_keys)

    monkeypatch.setattr(OSM, "_select_overpass_server_key", recording_select)
    return recorded_failed_sets


def _stub_post(monkeypatch, responses):
    """Serve ``responses`` (a _FakeResponse or an exception per attempt)
    and record what each attempt was sent with."""
    attempts = []
    remaining = list(responses)

    def fake_post(server_key, overpass_query, request_label="",
                  read_timeout_seconds=None):
        attempts.append(
            {
                "server_key": server_key,
                "query": overpass_query,
                "read_timeout_seconds": read_timeout_seconds,
            }
        )
        outcome = remaining.pop(0) if remaining else _good_response()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(
        OSM, "_post_overpass_query_reporting_progress", fake_post
    )
    return attempts


def test_failed_servers_are_excluded_until_pool_exhausted(
    monkeypatch, three_servers
):
    probed = []
    _stub_probe_to_first_candidate(monkeypatch, probed)

    key_one = OSM._select_overpass_server_key(three_servers, set())
    key_two = OSM._select_overpass_server_key(three_servers, {key_one})
    key_three = OSM._select_overpass_server_key(
        three_servers, {key_one, key_two}
    )
    assert {key_one, key_two, key_three} == set(three_servers)
    # With two of three servers failed only one candidate remains, so the
    # last pick must not have gone through the status probe.
    assert len(probed) == 2


def test_all_failed_falls_back_to_full_pool(monkeypatch, three_servers):
    probed = []
    _stub_probe_to_first_candidate(monkeypatch, probed)

    key = OSM._select_overpass_server_key(three_servers, set(three_servers))
    assert key in three_servers
    assert probed[-1] == three_servers


def test_pinned_choice_wins_even_after_failure(monkeypatch, three_servers):
    monkeypatch.setattr(OSM, "overpass_server_choice", "gamma")
    assert OSM._select_overpass_server_key(three_servers, {"gamma"}) == "gamma"


def test_request_rotates_through_every_server_before_repeating(
    monkeypatch, three_servers, captured_sleeps
):
    """End-to-end through get_overpass_data with every attempt failing:
    each server must be tried once before any server is tried again, and
    the exclusion round must reset once the pool is exhausted."""
    monkeypatch.setattr(OSM, "max_osm_tentatives", 5)
    probed = []
    _stub_probe_to_first_candidate(monkeypatch, probed)
    attempts = _stub_post(
        monkeypatch,
        [OSM.requests.RequestException("synthetic outage")] * 5,
    )

    assert OSM.get_overpass_data('way["highway"]', (0, 0, 1, 1)) == 0

    attempted_keys = [attempt["server_key"] for attempt in attempts]
    assert len(attempted_keys) == 5
    assert set(attempted_keys[:3]) == set(three_servers)
    # Round two starts over from the full pool.
    assert len(set(attempted_keys[3:])) == len(attempted_keys[3:])


def test_failure_clears_stickiness_for_the_next_request(
    monkeypatch, three_servers, captured_sleeps
):
    """A failed request must not leave the failing server sticky: the
    NEXT get_overpass_data call has to start somewhere else."""
    monkeypatch.setattr(OSM, "max_osm_tentatives", 1)
    monkeypatch.setattr(
        OSM.get_overpass_data,
        "last_successful_server_key",
        "beta",
        raising=False,
    )
    probed = []
    _stub_probe_to_first_candidate(monkeypatch, probed)

    first_attempts = _stub_post(
        monkeypatch, [OSM.requests.RequestException("synthetic outage")]
    )
    assert OSM.get_overpass_data('way["highway"]', (0, 0, 1, 1)) == 0
    assert first_attempts[0]["server_key"] == "beta"
    assert (
        getattr(OSM.get_overpass_data, "last_successful_server_key", None)
        is None
    )

    second_attempts = _stub_post(monkeypatch, [_good_response()])
    assert OSM.get_overpass_data('way["highway"]', (0, 0, 1, 1)) == b"<osm></osm>"
    assert second_attempts[0]["server_key"] != "beta"
    # Stickiness is re-earned by the success.
    assert (
        OSM.get_overpass_data.last_successful_server_key
        == second_attempts[0]["server_key"]
    )


def test_short_retry_after_retries_the_same_server(
    monkeypatch, three_servers, captured_sleeps
):
    monkeypatch.setattr(OSM, "max_osm_tentatives", 2)
    monkeypatch.setattr(
        OSM.get_overpass_data,
        "last_successful_server_key",
        "beta",
        raising=False,
    )
    _stub_probe_to_first_candidate(monkeypatch, [])
    recorded_failed_sets = _record_selection_inputs(monkeypatch)
    attempts = _stub_post(
        monkeypatch, [_rate_limited_response("5"), _good_response()]
    )

    assert OSM.get_overpass_data('way["highway"]', (0, 0, 1, 1)) == b"<osm></osm>"
    assert [attempt["server_key"] for attempt in attempts] == ["beta", "beta"]
    # The rate-limited server was neither excluded nor unstuck.
    assert recorded_failed_sets == [set(), set()]
    assert sum(captured_sleeps) == 5


def test_long_retry_after_rotates_with_capped_wait(
    monkeypatch, three_servers, captured_sleeps
):
    monkeypatch.setattr(OSM, "max_osm_tentatives", 2)
    monkeypatch.setattr(
        OSM.get_overpass_data,
        "last_successful_server_key",
        "beta",
        raising=False,
    )
    _stub_probe_to_first_candidate(monkeypatch, [])
    recorded_failed_sets = _record_selection_inputs(monkeypatch)
    attempts = _stub_post(
        monkeypatch, [_rate_limited_response("300"), _good_response()]
    )

    assert OSM.get_overpass_data('way["highway"]', (0, 0, 1, 1)) == b"<osm></osm>"
    assert attempts[0]["server_key"] == "beta"
    assert attempts[1]["server_key"] != "beta"
    assert recorded_failed_sets == [set(), {"beta"}]
    assert sum(captured_sleeps) == 120


def test_missing_retry_after_uses_the_status_probe_slot(
    monkeypatch, three_servers, captured_sleeps
):
    """FOSSGIS 429s carry no Retry-After; the server's own status page
    then says when our next slot frees."""
    monkeypatch.setattr(OSM, "max_osm_tentatives", 2)
    monkeypatch.setattr(
        OSM.get_overpass_data,
        "last_successful_server_key",
        "beta",
        raising=False,
    )
    _stub_probe_to_first_candidate(monkeypatch, [])
    monkeypatch.setattr(
        OSM,
        "_read_overpass_server_status",
        lambda server_key: {
            "slots_available_now": 0,
            "seconds_until_next_free_slot": 7.0,
            "probe_round_trip_seconds": 0.1,
        },
    )
    recorded_failed_sets = _record_selection_inputs(monkeypatch)
    attempts = _stub_post(
        monkeypatch, [_rate_limited_response(None), _good_response()]
    )

    assert OSM.get_overpass_data('way["highway"]', (0, 0, 1, 1)) == b"<osm></osm>"
    assert [attempt["server_key"] for attempt in attempts] == ["beta", "beta"]
    assert recorded_failed_sets == [set(), set()]
    assert sum(captured_sleeps) == 7


def test_long_probe_slot_time_does_not_inflate_the_rotation_wait(
    monkeypatch, three_servers, captured_sleeps
):
    """A probe-derived slot time binds only a same-server wait: once the
    next attempt rotates elsewhere that server's slot time is
    meaningless, so the plain exponential backoff stands."""
    monkeypatch.setattr(OSM, "max_osm_tentatives", 2)
    monkeypatch.setattr(
        OSM.get_overpass_data,
        "last_successful_server_key",
        "beta",
        raising=False,
    )
    _stub_probe_to_first_candidate(monkeypatch, [])
    monkeypatch.setattr(
        OSM,
        "_read_overpass_server_status",
        lambda server_key: {
            "slots_available_now": 0,
            "seconds_until_next_free_slot": 90.0,
            "probe_round_trip_seconds": 0.1,
        },
    )
    recorded_failed_sets = _record_selection_inputs(monkeypatch)
    attempts = _stub_post(
        monkeypatch, [_rate_limited_response(None), _good_response()]
    )

    assert OSM.get_overpass_data('way["highway"]', (0, 0, 1, 1)) == b"<osm></osm>"
    assert attempts[0]["server_key"] == "beta"
    assert attempts[1]["server_key"] != "beta"
    assert recorded_failed_sets == [set(), {"beta"}]
    assert sum(captured_sleeps) == 2


def test_missing_retry_after_with_dead_probe_rotates(
    monkeypatch, three_servers, captured_sleeps
):
    monkeypatch.setattr(OSM, "max_osm_tentatives", 2)
    monkeypatch.setattr(
        OSM.get_overpass_data,
        "last_successful_server_key",
        "beta",
        raising=False,
    )
    _stub_probe_to_first_candidate(monkeypatch, [])
    monkeypatch.setattr(
        OSM, "_read_overpass_server_status", lambda server_key: None
    )
    recorded_failed_sets = _record_selection_inputs(monkeypatch)
    attempts = _stub_post(
        monkeypatch, [_rate_limited_response(None), _good_response()]
    )

    assert OSM.get_overpass_data('way["highway"]', (0, 0, 1, 1)) == b"<osm></osm>"
    assert attempts[1]["server_key"] != "beta"
    assert recorded_failed_sets == [set(), {"beta"}]
    assert sum(captured_sleeps) == 2


def test_patience_escalates_from_quick_to_full_window(
    monkeypatch, three_servers, captured_sleeps
):
    monkeypatch.setattr(OSM, "max_osm_tentatives", 3)
    _stub_probe_to_first_candidate(monkeypatch, [])
    attempts = _stub_post(
        monkeypatch,
        [
            OSM.requests.RequestException("synthetic outage"),
            OSM.requests.RequestException("synthetic outage"),
            _good_response(),
        ],
    )

    assert OSM.get_overpass_data('way["highway"]', (0, 0, 1, 1)) == b"<osm></osm>"
    for attempt in attempts[:2]:
        assert "[timeout:60]" in attempt["query"]
        assert attempt["read_timeout_seconds"] == 75
    assert "[timeout:180]" in attempts[2]["query"]
    assert attempts[2]["read_timeout_seconds"] == 210


def test_silent_status_probe_is_retried_once(monkeypatch, three_servers):
    """A server whose first /api/status probe times out is selectable
    again once the retry round gets an answer out of it."""
    probe_counts = {}
    free_slot_report = {
        "slots_available_now": 1,
        "seconds_until_next_free_slot": 0.0,
        "probe_round_trip_seconds": 0.1,
    }

    def flaky_probe(server_key):
        probe_counts[server_key] = probe_counts.get(server_key, 0) + 1
        if server_key != "beta":
            return None
        return None if probe_counts[server_key] == 1 else dict(free_slot_report)

    monkeypatch.setattr(OSM, "_read_overpass_server_status", flaky_probe)

    assert OSM._select_most_available_server_key(three_servers) == "beta"
    assert probe_counts["beta"] == 2
