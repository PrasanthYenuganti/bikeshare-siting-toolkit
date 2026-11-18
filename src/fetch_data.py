"""Step 1: download the open data for one city into data/<city>/raw/.

Usage:
    python src/fetch_data.py config/marica.json

Sources: the city boundary (any GeoJSON URL in the config), OpenStreetMap via
the Overpass API, and existing stations from a GBFS feed or a CSV you supply.
"""
import csv
import os
import sys
import time

import requests

from common import data_dir, load_config, write_json

OVERPASS = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "bikeshare-siting-toolkit/1.0 (open-source research)"}

SERVICE_RE = "school|college|university|hospital|clinic|doctors|pharmacy|bank|marketplace|townhall|library|police|bus_station"
ROAD_RE = "^(primary|secondary|tertiary|trunk|residential|living_street|unclassified|pedestrian)$"


def overpass(query, label, tries=5):
    for attempt in range(1, tries + 1):
        print(f"  Overpass: {label} (attempt {attempt})")
        try:
            r = requests.post(OVERPASS, data={"data": query}, headers=HEADERS, timeout=300)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(20 * attempt)
                continue
            r.raise_for_status()
            return r.json()["elements"]
        except (requests.RequestException, ValueError) as e:
            print(f"    failed: {e}")
            time.sleep(15 * attempt)
    sys.exit(f"Overpass kept failing for {label}. Wait a few minutes and run again.")


def main(cfg_path):
    cfg = load_config(cfg_path)
    raw = data_dir(cfg, "raw")
    s, w, n, e = cfg["bbox"]
    bb = f"({s},{w},{n},{e})"
    print(f"Fetching data for {cfg['name']}")

    print("  Boundary")
    r = requests.get(cfg["boundary_url"], headers=HEADERS, timeout=120)
    r.raise_for_status()
    write_json(os.path.join(raw, "boundary.geojson"), r.json())

    q_points = f"""[out:json][timeout:180];(
      node["highway"="bus_stop"]{bb};node["public_transport"="platform"]["bus"="yes"]{bb};
      node["amenity"~"{SERVICE_RE}"]{bb};way["amenity"~"{SERVICE_RE}"]{bb};
      node["shop"]{bb};way["shop"~"supermarket|mall"]{bb};
      node["amenity"="bicycle_rental"]{bb};
      node["place"~"suburb|neighbourhood|quarter|village|town|city"]{bb};
    );out center tags;"""
    write_json(os.path.join(raw, "osm_points.json"), overpass(q_points, "stops, services, shops, places"))
    time.sleep(10)

    cyc = "|".join(["lane", "track"])
    q_ways = f"""[out:json][timeout:240];(
      way["highway"~"{ROAD_RE}"]{bb};way["highway"="cycleway"]{bb};
      way["cycleway"~"{cyc}"]{bb};way["cycleway:both"~"{cyc}"]{bb};
      way["cycleway:left"~"{cyc}"]{bb};way["cycleway:right"~"{cyc}"]{bb};
    );out tags geom;"""
    write_json(os.path.join(raw, "osm_ways.json"), overpass(q_ways, "streets and cycleways"))
    time.sleep(10)

    q_bld = f"""[out:json][timeout:240];way["building"]{bb};out center;"""
    write_json(os.path.join(raw, "osm_buildings.json"), overpass(q_bld, "buildings"))
    time.sleep(10)

    q_water = f"""[out:json][timeout:180];(way["natural"="water"]{bb};rel["natural"="water"]{bb};);out geom;"""
    write_json(os.path.join(raw, "osm_water.json"), overpass(q_water, "water bodies"))

    gbfs = cfg.get("gbfs_station_information")
    out_csv = os.path.join(data_dir(cfg), "stations.csv")
    if gbfs:
        print("  Stations from GBFS")
        st = requests.get(gbfs, headers=HEADERS, timeout=60).json()["data"]["stations"]
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(["station_id", "name", "lat", "lon", "source"])
            for x in st:
                wr.writerow([x["station_id"], x.get("name", ""), x["lat"], x["lon"], "GBFS"])
    elif not os.path.exists(out_csv):
        sys.exit(f"No GBFS feed in the config and no {out_csv}. Add a stations CSV with lat and lon columns.")
    print("Done. Next: python src/build_grid.py", cfg_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/fetch_data.py config/<city>.json")
    main(sys.argv[1])
