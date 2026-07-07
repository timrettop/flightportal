"""Fixture test for FlightRadar24 parsing + classification.

Loads a real (curated) FR24 feed response and runs each row through the same
parse_fr24_row() that code.py's get_flights() uses -- so if an upstream feed
change shifts a column, or someone edits an index in the parser, these
assertions fail instead of the board silently mislabeling flights.

Run from the repo root:
    pytest
"""
import json
import os

import pytest
from flightlogic import parse_fr24_row, classify_flight

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "fr24_sample.json")
HOME = "ORD"
# East-flow test settings, so the two blank-route rows classify deterministically
# by heading. Route-based rows don't depend on these.
ARRIVAL_HEADING = 90
HEADING_TOLERANCE = 50
META_KEYS = ("full_count", "version")


@pytest.fixture(scope="module")
def feed():
    with open(FIXTURE) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def flights(feed):
    # same skip rule get_flights uses: drop metadata + too-short rows
    return {k: v for k, v in feed.items()
            if k not in META_KEYS and len(v) > 13}


def test_fixture_shape(feed, flights):
    for k in META_KEYS:
        assert k in feed, f"metadata key {k} missing from fixture"
    assert len(flights) == 14


# ---- lock the actual field indices against a known row ----
def test_parse_pins_indices(flights):
    p = parse_fr24_row("4089b2e1", flights["4089b2e1"])
    assert p["lat"] == 41.7712
    assert p["lon"] == -87.5911
    assert p["heading"] == 305
    assert p["alt"] == 9875
    assert p["aircraft"] == "A319"
    assert p["origin"] == "MDT"
    assert p["dest"] == "ORD"
    assert p["callsign"] == "AA3243"      # from fi[13]


def test_callsign_fallback_to_fi16(flights):
    # fi[13] is empty here, so the callsign should fall back to fi[16]
    p = parse_fr24_row("4089bc09", flights["4089bc09"])
    assert p["origin"] == ""
    assert p["dest"] == ""
    assert p["callsign"] == "C172"        # fi[13]=="" -> fi[16]=="C172"


# ---- classification of every row, pinned against the real feed ----
EXPECTED = {
    "40896167": "unknown",    # SEA->EWR overflight (37000 ft)
    "4089dd2a": "unknown",    # DTW->MCI overflight
    "4089b2e1": "arrival",    # MDT->ORD
    "4089e3e8": "departure",  # ORD->DOH
    "40891952": "arrival",    # ANC->ORD
    "4089a3cb": "arrival",    # EWR->ORD
    "4089ed98": "departure",  # ORD->SEA
    "4089db83": "departure",  # ORD->AUS
    "4089e61c": "unknown",    # MDW->CLE (nearby field, not home)
    "4089b716": "arrival",    # blank route, hdg 43 -> heading fallback
    "4089cb1f": "arrival",    # XNA->ORD
    "4089f0d5": "departure",  # ORD->BUF
    "4089bc09": "departure",  # blank route, hdg 235 -> heading fallback
    "4089b686": "unknown",    # blank route, hdg 344 off-corridor (also a heli)
}


@pytest.mark.parametrize("fid,expected", list(EXPECTED.items()))
def test_classification(flights, fid, expected):
    p = parse_fr24_row(fid, flights[fid])
    cls = classify_flight(p["origin"], p["dest"], p["heading"], HOME,
                          ARRIVAL_HEADING, HEADING_TOLERANCE)
    assert cls == expected


def test_every_flight_has_expectation(flights):
    # guards against adding a fixture row without a pinned expectation
    assert set(flights) == set(EXPECTED)
