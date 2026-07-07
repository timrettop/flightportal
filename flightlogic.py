# flightlogic.py
#
# Pure flight-classification logic for FlightPortal. Deliberately imports
# nothing hardware- or network-related, so it runs on a normal computer and
# can be unit-tested off the MatrixPortal. Keep it that way -- if you find
# yourself importing `board`, `wifi`, or `displayio` here, it belongs in
# code.py instead.
#
# NOTE: this file must also be copied to the CIRCUITPY drive alongside
# code.py, since code.py imports it at runtime.


def angular_diff(a, b):
    """Smallest difference between two compass bearings, in degrees (0..180).

    Handles wraparound: angular_diff(350, 10) == 20, not 340.
    """
    d = abs((a - b) % 360)
    return d if d <= 180 else 360 - d


def classify_flight(origin, dest, heading, home_airport,
                    arrival_heading=None, heading_tolerance=50):
    """Classify a flight as 'arrival', 'departure', or 'unknown'.

    Route first (most reliable):
      - destination is the home airport -> 'arrival'
      - origin is the home airport      -> 'departure'
      - both ends known, neither is home -> 'unknown' (an overflight)

    If the route is blank, fall back to heading: arrivals fly roughly along
    `arrival_heading`, departures along its reciprocal. If the track is within
    `heading_tolerance` degrees of one of those, classify it; otherwise
    'unknown'.
    """
    home = (home_airport or "").upper()
    o = (origin or "").upper()
    d = (dest or "").upper()

    if home:
        if d and d == home:
            return "arrival"
        if o and o == home:
            return "departure"
        if o and d:
            return "unknown"   # overflight: both ends known, neither is home

    if arrival_heading is None or heading is None:
        return "unknown"

    to_arrival = angular_diff(heading, arrival_heading)
    to_departure = angular_diff(heading, (arrival_heading + 180) % 360)
    if min(to_arrival, to_departure) > heading_tolerance:
        return "unknown"
    return "arrival" if to_arrival <= to_departure else "departure"


def queue_mode(classes):
    """Decide which runway intro to play for the current queue.

    Returns 'arrivals', 'departures', or 'mixed'. 'unknown' entries are
    ignored, so one unclassified flight doesn't suppress the intro for an
    otherwise homogeneous queue.
    """
    arrivals = 0
    departures = 0
    for c in classes:
        if c == "arrival":
            arrivals += 1
        elif c == "departure":
            departures += 1
    if arrivals and not departures:
        return "arrivals"
    if departures and not arrivals:
        return "departures"
    return "mixed"


def resolve_route(origin, dest, cls, home_airport):
    """Fill in the home end of a route when classification knows it but the
    feed left it blank, for nicer display. Returns (origin, dest).
    """
    home = home_airport or ""
    o = origin or ""
    d = dest or ""
    if cls == "arrival" and not d:
        d = home
    elif cls == "departure" and not o:
        o = home
    return o, d


def passes_direction_filter(cls, show_arrivals, show_departures):
    """Whether a flight should be shown given the arrival/departure toggles.

    'unknown' is always shown -- we won't hide what we can't confidently
    classify.
    """
    if cls == "arrival":
        return show_arrivals
    if cls == "departure":
        return show_departures
    return True


def parse_fr24_row(fid, fi):
    """Extract the fields FlightPortal uses from one FlightRadar24 feed row.

    The feed encodes each aircraft as a positional list; this function is the
    single definition of which index means what, shared by code.py's
    get_flights() and the tests. `fid` is the feed key, used as the last
    callsign fallback. Missing indices fall back to safe defaults so a short
    or malformed row can't raise.
    """
    def at(i, default=None):
        return fi[i] if len(fi) > i else default

    return {
        "id": fid,
        "lat": at(1, 0),
        "lon": at(2, 0),
        "heading": at(3, 0),
        "alt": at(4, 99999),
        "aircraft": at(8) or "?",
        "origin": at(11) or "",
        "dest": at(12) or "",
        "callsign": at(13) or at(16) or fid,
    }

