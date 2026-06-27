config = {
    'bounds_box':         'your bounds', # N,S,W,E  - for fr24 api
    'radius_nm':           25, # radius in nautical miles - for adsb.lol
    'home_airport':       'ZRH',
    'filter_destination': False,
    'filter_origin':      False,
    'filter_arrivals':    False,
    'filter_departures':  False,
    'filter_altitude':    False,
    'min_altitude':       0,    # only applicable if filter_altitude is True
    'max_altitude':       10000, # only applicable if filter_altitude is True
    'filter_direction':   False,
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
