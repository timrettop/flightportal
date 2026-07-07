# demo_feed.py -- scripted flight data for exercising the display on-device
# without waiting for live traffic. Enable with 'demo_mode': True in config.py.
# Copy this file to the CIRCUITPY drive alongside code.py when demo_mode is on.
#
# Each call returns the next scenario in a repeating cycle, so you can watch
# the intro animations and the mode-transition guard in order:
#
#   step 1: arrivals only    -> landing intro plays
#   step 2: arrivals only    -> intro does NOT replay (mode unchanged)
#   step 3: departures only  -> takeoff intro plays
#   step 4: mixed            -> no intro
#   step 5: empty            -> weather screen (last_mode resets)
#   ...then repeats from step 1 (landing intro plays again).
#
# Classification is route-first, so arrivals have dest == home and departures
# have origin == home -- the modes are deterministic regardless of heading.

_step = 0


def _row(heading, origin, dest, callsign, actype="A320"):
    r = [None] * 19
    vals = {3: heading, 5: 250, 8: actype, 11: origin,
            12: dest, 13: callsign, 16: callsign, 18: ""}
    for i, v in vals.items():
        r[i] = v
    return r

# Set home to match config's home_airport; ORD by default.
_HOME = "ORD"

_SCENARIOS = [
    # arrivals only
    {"DEMO1": _row(270, "SFO", _HOME, "UAL100", "B739"),
     "DEMO2": _row(268, "DEN", _HOME, "AAL200", "A320")},
    # arrivals only again (proves the intro does not replay)
    {"DEMO1": _row(271, "SEA", _HOME, "UAL101", "B738"),
     "DEMO2": _row(269, "LAX", _HOME, "AAL201", "A321")},
    # departures only
    {"DEMO3": _row(90, _HOME, "JFK", "UAL300", "B752"),
     "DEMO4": _row(92, _HOME, "LAX", "AAL400", "A321")},
    # mixed
    {"DEMO5": _row(270, "BOS", _HOME, "UAL500", "B738"),
     "DEMO6": _row(90,  _HOME, "MIA", "AAL600", "A319")},
    # empty -> weather
    {},
]


def get_flights_demo(url, headers):
    """Drop-in replacement for get_flights(). Returns (flights, raw) in the
    same shape, cycling through the scenarios above."""
    global _step
    raw = _SCENARIOS[_step % len(_SCENARIOS)]
    _step += 1

    flights = []
    for i, (fid, fi) in enumerate(raw.items()):
        o = fi[11] or ""
        d = fi[12] or ""
        dist = 3.0 + i     # fake distance (km), ascending so the sort is stable
        alt = 4000         # cosmetic here; demo bypasses the real altitude filter
        flights.append((fid, o, d, dist, alt))
    return flights, raw
