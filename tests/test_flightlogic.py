"""Tests for flightlogic.py.

Run from the repo root:
    pip install pytest hypothesis
    pytest

The plain tests need only pytest. The property-based tests at the bottom
need hypothesis; they're skipped automatically if it isn't installed.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from flightlogic import (
    angular_diff,
    classify_flight,
    queue_mode,
    resolve_route,
    passes_direction_filter,
)

HOME = "ZRH"


# ---- angular_diff ----
@pytest.mark.parametrize("a,b,expected", [
    (0, 0, 0),
    (10, 350, 20),      # wraparound
    (350, 10, 20),      # wraparound, other direction
    (0, 180, 180),
    (90, 270, 180),
    (270, 240, 30),
    (359, 1, 2),
])
def test_angular_diff(a, b, expected):
    assert angular_diff(a, b) == expected


# ---- classify_flight: route-based ----
@pytest.mark.parametrize("o,d,expected", [
    ("LHR", "ZRH", "arrival"),
    ("ZRH", "LHR", "departure"),
    ("LHR", "CDG", "unknown"),     # overflight, neither end is home
    ("lhr", "zrh", "arrival"),     # case-insensitive
])
def test_classify_by_route(o, d, expected):
    assert classify_flight(o, d, 270, HOME, arrival_heading=270) == expected


def test_route_beats_heading():
    # dest is home -> arrival, even though heading 90 would say departure
    assert classify_flight("LHR", "ZRH", 90, HOME, arrival_heading=270) == "arrival"


def test_partial_route_still_classifies():
    # only the home end is known
    assert classify_flight("", "ZRH", None, HOME) == "arrival"
    assert classify_flight("ZRH", "", None, HOME) == "departure"


# ---- classify_flight: heading fallback ----
@pytest.mark.parametrize("heading,expected", [
    (270, "arrival"),      # on the arrival course
    (90, "departure"),     # reciprocal
    (255, "arrival"),      # within tolerance of arrival
    (0, "unknown"),        # off-corridor beyond tolerance
])
def test_classify_by_heading(heading, expected):
    assert classify_flight("", "", heading, HOME,
                           arrival_heading=270, heading_tolerance=50) == expected


def test_heading_needs_arrival_course():
    # no arrival_heading configured -> can't fall back
    assert classify_flight("", "", 270, HOME) == "unknown"


def test_heading_wraparound_corridor():
    # arrival course near north; a track at 5 deg should still classify
    assert classify_flight("", "", 5, HOME,
                           arrival_heading=350, heading_tolerance=30) == "arrival"


# ---- queue_mode ----
@pytest.mark.parametrize("classes,expected", [
    (["arrival", "arrival"], "arrivals"),
    (["departure"], "departures"),
    (["arrival", "departure"], "mixed"),
    (["arrival", "unknown"], "arrivals"),     # unknown ignored
    (["departure", "unknown"], "departures"),
    (["unknown", "unknown"], "mixed"),        # nothing to key on
    ([], "mixed"),
])
def test_queue_mode(classes, expected):
    assert queue_mode(classes) == expected


# ---- resolve_route ----
def test_resolve_fills_home_end():
    assert resolve_route("LHR", "", "arrival", HOME) == ("LHR", "ZRH")
    assert resolve_route("", "LHR", "departure", HOME) == ("ZRH", "LHR")
    assert resolve_route("LHR", "CDG", "unknown", HOME) == ("LHR", "CDG")


# ---- passes_direction_filter ----
@pytest.mark.parametrize("cls,show_arr,show_dep,expected", [
    ("arrival", True, False, True),
    ("arrival", False, False, False),
    ("departure", True, False, False),
    ("departure", True, True, True),
    ("unknown", False, False, True),          # unknown always shown
])
def test_direction_filter(cls, show_arr, show_dep, expected):
    assert passes_direction_filter(cls, show_arr, show_dep) is expected


# ---- property-based (optional: pip install hypothesis) ----
try:
    from hypothesis import given, strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

if HAS_HYPOTHESIS:

    @given(a=st.floats(0, 360), b=st.floats(0, 360))
    def test_angular_diff_bounded(a, b):
        assert 0 <= angular_diff(a, b) <= 180

    @given(a=st.floats(0, 360), b=st.floats(0, 360))
    def test_angular_diff_symmetric(a, b):
        # symmetric up to float rounding of the two modulo ops; real
        # headings are integers, where it's exact
        assert angular_diff(a, b) == pytest.approx(angular_diff(b, a))

    @given(
        o=st.sampled_from(["", "ZRH", "LHR", "CDG"]),
        d=st.sampled_from(["", "ZRH", "LHR", "CDG"]),
        h=st.floats(0, 360),
    )
    def test_classify_returns_valid_label(o, d, h):
        assert classify_flight(o, d, h, HOME, arrival_heading=270) in (
            "arrival", "departure", "unknown")

    @given(classes=st.lists(st.sampled_from(["arrival", "departure", "unknown"])))
    def test_queue_mode_never_contradicts(classes):
        m = queue_mode(classes)
        # arrivals intro is never chosen when any departure is present
        if m == "arrivals":
            assert "departure" not in classes
        if m == "departures":
            assert "arrival" not in classes
