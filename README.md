# FlightPortal

A slimmed down flight and weather tracker for a 64×32 RGB LED matrix, built on the Adafruit MatrixPortal S3.

> Credit to [smartbutnot](https://github.com/smartbutnot/) for the original project this is based on and [solomonreal](https://github.com/solomonreal) for the port to S3.

![FlightPortal](https://user-images.githubusercontent.com/103124527/208709167-dd4b6ff2-4c80-4e38-840f-e5b958e2ed78.jpg)

---

## What it does

### Flights

Polls FlightRadar24 every 30 seconds for aircraft overhead. When one or more flights are detected it displays a list of aircraft that meet the defined filters. This version is designed for viewpoints on a landing/takeoff flight path.  Ordering is based on distance from 'MY_LON and MY_LAT'. Optional filters available.  

Missing flight data is enriched automatically via adsb.lol and hexdb.io. Planespotters.net support exists in the code for private jets/charter operators but is currently non-functional (missing URL constant). OpenSky support is present but not yet connected to the main lookup flow.

### Weather

Shown weather and temperature of configured airport between flights. Displays temperature in a colour that shifts from blue (freezing) through cyan, green and yellow to red (hot), alongside condition text and wind speed. Shows sunrise time before midday and sunset time after.

---

## Hardware

1. [Adafruit MatrixPortal S3](<https://learn.adafruit.com/adafruit-matrixportal-s3>)
2. P4 64×32 RGB matrix panel (<https://www.adafruit.com/product/2278>)
3. [Case (Thingiverse)](<https://www.thingiverse.com/thing:5701517>)
4. [Adafruit acrylic diffuser](<https://www.adafruit.com/product/4749>)
5. 6× M3 screws (~8mm)
6. Optional: [Uglu dashes](<https://www.protapes.com/products/uglu-600-dashes-sheets>) to secure the diffuser

---

## Setup

Prep the MatrixPortal following [Adafruit's guide](<https://learn.adafruit.com/adafruit-matrixportal-s3/prep-the-matrixportal>).

Copy the following to the root of the CIRCUITPY drive:

```text
boot.py
code.py
flightlogic.py
config.py       (copied from config.py.example, see below)
secrets.py      (copied from secrets.py.example, see below)
settings.toml   (copied from settings.toml.example, see below)
ota/            (the whole folder)
```

boot.py` and everything under `ota/` are what make [over-the-air updates](#updates)
possible — see that section for what's safe to skip if you don't want OTA.

None of `config.py`, `secrets.py`, or `settings.toml` are committed to this
repo — only their `.example` counterparts are. Copy each one, drop the
`.example` suffix, and fill in your own values. These three are split by what
kind of data they hold, and OTA updates never touch any of them:

### `settings.toml` - network credentials

```toml
CIRCUITPY_WIFI_SSID = "your_wifi_ssid"
CIRCUITPY_WIFI_PASSWORD = "your_wifi_password"
 
# Optional -- enables instant push updates instead of hourly polling only.
# See "Updates" below. Leave as the placeholder values (or blank) to skip.
AIO_USERNAME = "your_aio_username"
AIO_KEY = "your_aio_key"
```

### `secrets.py` — personally-identifying data

```python
secrets = {
    'my_lat': 0.0000,
    'my_lon': 0.0000,
}
```

### `config.py` — everything else configurable

```python
config = {
    'bounds_box':          '',     # N,S,W,E -- see below
    'home_airport':        'ZRH',
    'demo_mode':            False,
 
    'filter_direction':     False,
    'heading_min':           240,
    'heading_max':           300,
    # 'arrival_heading':     None,  # optional override, defaults to the midpoint of heading_min/max
    'min_altitude':            0,
    'max_altitude':         7000,
    'show_arrivals':         True,
    'show_departures':       True,
    'heading_tolerance':      50,
 
    'temp_unit':              'F',
    'timezone':          'UTC',
    'show_full_aircraft':   False,
    'show_helicopters':     False,
 
    # Feature flags
    'enable_flights':        True,
    'enable_weather':        True,
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

---

## Updates

Application code updates itself over the air — no USB required after the
initial setup above. GitHub Actions builds and cryptographically signs each
release; the device verifies that signature before installing anything.

**What ships automatically**, defined in [`ota-files.txt`](ota-files.txt):

- `code.py`
- `flightlogic.py`
- `ota/updater.py`
- `ota/doorbell.py`
- `ota/__init__.py`
**What never ships**, whatever a release contains — enforced on both the
device (`ota/updater.py`) and the build script (`tools/make_manifest.py`),
so a mistake in one doesn't bypass the other:

- `boot.py`, and the rest of `ota/` except the two files above (the trusted
  core — installed once via USB, never touched afterward)
- `settings.toml`, `secrets.py`, `config.py` — all local to your device

**How a device gets an update:**

1. Checks hourly by default.
2. If `AIO_USERNAME`/`AIO_KEY` are set in `settings.toml`, it also subscribes
   to an MQTT feed and updates within seconds of a release publishing,
   instead of waiting for the hourly check.
3. Every manifest is signature-verified and version-checked (no downgrades)
   before anything is written to flash. A failed or partial update rolls
   back automatically on the next boot.

### One-time setup

**1. Generate the signing key:**

```bash
pip install cryptography
python3 tools/keygen.py
```

Writes `ota-private.pem` (keep this out of the repo — add it to
`.gitignore`) and overwrites `ota/pubkey.py` with your real public key.
Commit `ota/pubkey.py`; it needs to be on the device (via USB, as part of
the file list above) before any signed update will verify.

**2. Add the signing key as a GitHub Actions secret:**

- **Settings → Environments → New environment**, name it `ota-signing`.
  Under deployment protection rules, add yourself as a required reviewer —
  this makes every release wait for manual approval before it can sign
  anything, so pushing a tag alone can't get code onto the device.
- Inside that environment's own secrets section (not the repo-level one),
  add a secret named `OTA_SIGNING_KEY` with the full contents of
  `ota-private.pem`.
**3. (Optional) Set up instant push updates via Adafruit IO**, instead of
relying on the hourly check alone:

- Sign in at [io.adafruit.com](https://io.adafruit.com), click your
  profile icon → **View AIO Key** for your username and key.
- **Feeds → Actions → Create a New Feed**, name it `ota`.
- Add both as **repository-level** secrets (not scoped to `ota-signing` —
  they're low-stakes compared to the signing key, so there's no need to
  gate them behind the same approval): `AIO_USERNAME` and `AIO_KEY`.
- Add the same two values to `settings.toml` on the device, as shown in
  [Setup](#setup) above. Leave them blank (or as the placeholder values) to
  skip this and use hourly polling only — the device detects that
  automatically and falls back cleanly, with no error.

### Cutting a release

```bash
git tag -a v3 -m "describe what changed"
git push origin v3
```

Any push of a tag matching `v*` triggers the release workflow. It builds
the manifest from whatever's listed in `ota-files.txt`, signs it, and waits
for approval in the Actions tab (the `ota-signing` environment gate from
step 2 above). Approve it, and the workflow publishes the release; devices
pick it up on their next check, or within seconds if the MQTT push is
configured.

The tag name itself (`v3`, `v4`, ...) is just what triggers the workflow —
it doesn't need to be sequential or meaningful beyond your own changelog.
The version number devices actually compare against for rollback protection
is derived automatically from the commit count at release time, so there's
nothing to keep in sync between the two.
