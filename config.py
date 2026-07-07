config = {
    'bounds_box':         'your bounds', # N,S,W,E  - for fr24 api
    'home_airport':       'ZRH',
    'filter_direction':   False,
    'show_arrivals':      True,
    'show_departures':    True,
    'arrival_heading':    270,  # compass heading planes fly on approach over you; departures assumed reciprocal
    'heading_tolerance':  50,   # +/- degrees around that course for heading-based classification
    'heading_min':        240,  # only applicable if filter_direction is True
    'heading_max':        300,  # only applicable if filter_direction is True
    'temp_unit':          'F',  # 'F' or 'C'
    'timezone':           'UTC', # e.g. 'Europe/Zurich'
    'show_full_aircraft': False,
    'show_helicopters':   False,

    # Feature flags - set to False to disable
    'enable_flights':     True,
    'enable_weather':     True,
}
