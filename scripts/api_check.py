"""
FlightRadar24 vs adsb.lol API comparison test
Run with: python api_check.py
Requires: pip install requests
"""

import requests
import time
import json
from datetime import datetime

# ---- CONFIG - fill these in ----
MY_LAT      = 0   # your lat
MY_LON      = 0   # your lon
BOUNDS_BOX  = "0,0,0,0"  # your bounds box from secrets.py
RADIUS_NM   = 50       # adsb.lol search radius in nautical miles
RUNS        = 3        # how many times to query each API
RUN_DELAY   = 10       # seconds between runs

# ---- URLS ----
FR24_URL = (
    "https://data-cloud.flightradar24.com/zones/fcgi/feed.js"
    "?bounds=" + BOUNDS_BOX +
    "&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1"
    "&vehicles=0&estimated=0&maxage=14400&gliders=0&stats=0&ems=1"
)
ADSB_URL = f"https://api.adsb.lol/v2/lat/{MY_LAT}/lon/{MY_LON}/dist/{RADIUS_NM}/"

FR24_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:106.0) Gecko/20100101 Firefox/106.0",
    "cache-control": "no-store, no-cache, must-revalidate, post-check=0, pre-check=0",
    "Accept": "application/json"
}
ADSB_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}

def query_fr24():
    start = time.time()
    try:
        resp = requests.get(FR24_URL, headers=FR24_HEADERS, timeout=15)
        latency = time.time() - start
        if resp.status_code != 200:
            return None, latency, f"HTTP {resp.status_code}"
        data = resp.json()
        aircraft = []
        for fid, fi in data.items():
            if fid in ("version", "full_count") or not isinstance(fi, list) or len(fi) <= 13:
                continue
            aircraft.append({
                "id":       fid,
                "callsign": fi[13] or fi[16] or fid,
                "type":     fi[8] or "?",
                "lat":      fi[1],
                "lon":      fi[2],
                "heading":  fi[3],
                "alt":      fi[4],
                "speed":    fi[5],
                "origin":   fi[11] or "",
                "dest":     fi[12] or "",
                "seen":     None,   # FR24 doesn't provide this
            })
        return aircraft, latency, None
    except Exception as e:
        return None, time.time() - start, str(e)

def query_adsb():
    start = time.time()
    try:
        resp = requests.get(ADSB_URL, headers=ADSB_HEADERS, timeout=10)
        latency = time.time() - start
        if resp.status_code != 200:
            return None, latency, f"HTTP {resp.status_code}"
        data = resp.json()
        aircraft = []
        for ac in data.get("ac", []):
            aircraft.append({
                "id":       ac.get("hex",""),
                "callsign": (ac.get("flight","") or "").strip(),
                "type":     ac.get("t","") or "?",
                "lat":      ac.get("lat"),
                "lon":      ac.get("lon"),
                "heading":  ac.get("track") or ac.get("true_heading"),
                "alt":      ac.get("alt_baro") if ac.get("alt_baro") != "ground" else 0,
                "speed":    ac.get("gs"),
                "origin":   ac.get("orig","") or "",
                "dest":     ac.get("dest","") or "",
                "seen":     ac.get("seen"),
            })
        return aircraft, latency, None
    except Exception as e:
        return None, time.time() - start, str(e)

def compare_aircraft(fr24_list, adsb_list):
    """Find aircraft appearing in both feeds by callsign, compare fields."""
    fr24_by_cs = {a["callsign"].upper(): a for a in fr24_list if a["callsign"]}
    adsb_by_cs = {a["callsign"].upper(): a for a in adsb_list if a["callsign"]}

    both = set(fr24_by_cs.keys()) & set(adsb_by_cs.keys())
    only_fr24 = set(fr24_by_cs.keys()) - set(adsb_by_cs.keys())
    only_adsb = set(adsb_by_cs.keys()) - set(fr24_by_cs.keys())

    print(f"\n  Aircraft in both:      {len(both)}")
    print(f"  Only in FR24:          {len(only_fr24)}")
    print(f"  Only in adsb.lol:      {len(only_adsb)}")

    if both:
        print(f"\n  {'Callsign':<10} {'Type FR24':<10} {'Type ADSB':<10} "
              f"{'Alt FR24':>9} {'Alt ADSB':>9} {'Hdg FR24':>9} {'Hdg ADSB':>9} "
              f"{'Seen(s)':>8}")
        print("  " + "-"*80)
        for cs in sorted(both):
            f = fr24_by_cs[cs]
            a = adsb_by_cs[cs]
            seen = f"{a['seen']:.0f}" if a['seen'] is not None else "N/A"
            print(f"  {cs:<10} {f['type']:<10} {a['type']:<10} "
                  f"{str(f['alt']):>9} {str(a['alt']):>9} "
                  f"{str(f['heading']):>9} {str(a['heading']):>9} "
                  f"{seen:>8}")

    if only_fr24:
        print(f"\n  Only in FR24 ({len(only_fr24)}): {', '.join(sorted(only_fr24)[:10])}")
    if only_adsb:
        print(f"\n  Only in adsb.lol ({len(only_adsb)}): {', '.join(sorted(only_adsb)[:10])}")

def run_test():
    print("=" * 60)
    print(f"FlightRadar24 vs adsb.lol API Comparison Test")
    print(f"Location: {MY_LAT}, {MY_LON}")
    print(f"FR24 bounds: {BOUNDS_BOX}")
    print(f"adsb.lol radius: {RADIUS_NM}nm")
    print(f"Runs: {RUNS}, delay: {RUN_DELAY}s")
    print("=" * 60)

    fr24_latencies = []
    adsb_latencies = []
    fr24_counts = []
    adsb_counts = []

    for run in range(1, RUNS + 1):
        print(f"\n--- Run {run}/{RUNS} at {datetime.now().strftime('%H:%M:%S')} ---")

        print(f"\n  Querying FR24...")
        fr24_ac, fr24_lat, fr24_err = query_fr24()
        if fr24_err:
            print(f"  FR24 ERROR: {fr24_err}")
        else:
            fr24_latencies.append(fr24_lat)
            fr24_counts.append(len(fr24_ac))
            print(f"  FR24:     {len(fr24_ac):3d} aircraft  latency: {fr24_lat:.2f}s")

        print(f"\n  Querying adsb.lol...")
        adsb_ac, adsb_lat, adsb_err = query_adsb()
        if adsb_err:
            print(f"  adsb.lol ERROR: {adsb_err}")
        else:
            adsb_latencies.append(adsb_lat)
            adsb_counts.append(len(adsb_ac))
            print(f"  adsb.lol: {len(adsb_ac):3d} aircraft  latency: {adsb_lat:.2f}s")
            # show staleness distribution
            seen_vals = [a["seen"] for a in adsb_ac if a["seen"] is not None]
            if seen_vals:
                print(f"  adsb.lol staleness: min={min(seen_vals):.0f}s  "
                      f"avg={sum(seen_vals)/len(seen_vals):.0f}s  max={max(seen_vals):.0f}s")

        if fr24_ac and adsb_ac:
            compare_aircraft(fr24_ac, adsb_ac)

        if run < RUNS:
            print(f"\n  Waiting {RUN_DELAY}s...")
            time.sleep(RUN_DELAY)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if fr24_latencies:
        print(f"FR24     avg latency: {sum(fr24_latencies)/len(fr24_latencies):.2f}s  "
              f"avg aircraft: {sum(fr24_counts)/len(fr24_counts):.1f}")
    if adsb_latencies:
        print(f"adsb.lol avg latency: {sum(adsb_latencies)/len(adsb_latencies):.2f}s  "
              f"avg aircraft: {sum(adsb_counts)/len(adsb_counts):.1f}")

if __name__ == "__main__":
    run_test()
