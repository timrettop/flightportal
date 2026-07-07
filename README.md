# FlightPortal

A slimmed down flight and weather tracker for a 64×32 RGB LED matrix, built on the Adafruit MatrixPortal S3.

> Credit to [smartbutnot](https://github.com/smartbutnot/) for the original project this is based on and [solomonreal](https://github.com/solomonreal) for the port to S3.

![FlightPortal](https://user-images.githubusercontent.com/103124527/208709167-dd4b6ff2-4c80-4e38-840f-e5b958e2ed78.jpg)

---

## What it does

### Flights

Polls FlightRadar24 every 30 seconds for aircraft overhead. When one or more flights are detected it displays a list of aircraft that meet the defined filters. This version is designed for viewpoints on a landing/takeoff flight path.  Ordering is based on distance from 'MY_LON and MY_LAT'. Optional filters available.  

Missing flight data is enriched automatically via adsb.lol, OpenSky, hexdb.io and planespotters.net (good for private jets and charter operators). The static lookup covers 1,235 airports and 40+ airlines.

### Weather

Shown between flights. Displays temperature in a colour that shifts from blue (freezing) through cyan, green and yellow to red (hot), alongside condition text and wind speed. Shows sunrise time before midday and sunset time after.

---

## Hardware

1. [Adafruit MatrixPortal S3](https://learn.adafruit.com/adafruit-matrixportal-s3)
2. P4 64×32 RGB matrix panel (available on AliExpress)
3. [Case (Thingiverse)](https://www.thingiverse.com/thing:5701517)
4. [Adafruit acrylic diffuser](https://www.adafruit.com/product/4749)
5. 6× M3 screws (~8mm)
6. Optional: [Uglu dashes](https://www.protapes.com/products/uglu-600-dashes-sheets) to secure the diffuser

---

## Setup

Prep the MatrixPortal following [Adafruit's guide](https://learn.adafruit.com/adafruit-matrixportal-s3/prep-the-matrixportal), then copy `code.py` and `secrets.py` to the device.

### secrets.py

```python
secrets = {
    'ssid':            'your_wifi_ssid',
    'password':        'your_wifi_password',
    'bounds_box':      '',  # N,S,W,E
    'home_airport':    'ZRH',
    'football_key':    'optional_football_data_key',  # fallback only

    # Feature flags
    'enable_flights':  True,
    'enable_weather':  True,
}
```

The `bounds_box` is `north,south,west,east` in decimal degrees. Adjust it to the area visible from your window. A box of roughly 0.1° latitude × 0.1° longitude works well for a city location.

### Libraries

All included in the standard MatrixPortal prep. For reference:

```text
neopixel.mpy
adafruit_requests.mpy
adafruit_portalbase
adafruit_matrixportal
adafruit_display_text
adafruit_bitmap_font
adafruit_ticks.mpy
adafruit_json_stream.mpy
adafruit_datetime.mpy
adafruit_minimqtt
adafruit_io
adafruit_fakerequests.mpy
adafruit_esp32spi
```

### Power

Use the cable supplied with the matrix panel. Connect it to the portal's power port on the panel — power draw is around 2W so any decent USB power supply will do. Optionally solder directly to the panel's power port for a neater build.

![Wiring 1](https://user-images.githubusercontent.com/103124527/206903066-7af5c076-101e-4598-b3ba-0f64766e4162.jpg)
![Wiring 2](https://user-images.githubusercontent.com/103124527/206903084-42378ce0-b8d8-4810-a18a-f35b9a509752.jpg)

---

## APIs used

All free, no key required unless noted:

| Source | Used for |
| --- | --- |
| FlightRadar24 feed | Live flight positions |
| adsb.lol | Flight enrichment |
| OpenSky | Callsign / country |
| hexdb.io | Operator from hex code |
| planespotters.net | Private jet operators |
| Open-Meteo | Weather |
| Sofascore | Live football scores |
| football-data.org | Football fallback (optional key) |
| ESPN Cricinfo | Cricket scores |

---

## Debugging

Use PuTTY or a serial monitor. Find the COM port in Device Manager, connect at **115200 baud**. The code prints flight details, errors and API responses. You can also paste the feed URLs directly into a browser to check coverage for your area.
