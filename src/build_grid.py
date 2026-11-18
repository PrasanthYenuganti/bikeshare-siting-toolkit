"""Step 2: build the hexagon grid and measure every criterion per hexagon.

Usage:
    python src/build_grid.py config/marica.json

Reads data/<city>/raw/ (from fetch_data.py) and writes
data/<city>/hex_features.csv. Elevation comes from the Open-Meteo API and is
cached in data/<city>/raw/elevation.json so reruns do not call it again.
"""
import math
import os
import sys
import time

from common import (PointIndex, Projection, SegmentIndex, data_dir, hex_center, hex_of,
                    in_polygons, load_config, point_in_ring, polygons_from_geojson,
                    read_csv, read_json, write_csv, write_json)

RES_TYPES = {"residential", "living_street", "unclassified", "pedestrian"}
MAJOR_TYPES = {"primary", "secondary", "tertiary", "trunk"}
SERVICE_TYPES = {"school", "college", "university", "hospital", "clinic", "doctors", "pharmacy", "bank",
                 "marketplace", "townhall", "library", "police", "bus_station"}

FIELDS = ["q", "r", "lat", "lon", "zone", "place", "pop", "density", "pop600", "buildings", "res_street_m",
          "services600", "shops600", "bus_stops400", "bus_stop_m", "major_road_m", "cycleway_m",
          "station_m", "elev_m", "slope_pct"]


def is_cycleway(t):
    v = " ".join(str(t.get(k, "")) for k in ("cycleway", "cycleway:both", "cycleway:left", "cycleway:right"))
    return t.get("highway") == "cycleway" or "lane" in v or "track" in v


def fetch_elevation(cells, cache_path):
    import requests
    cache = read_json(cache_path) if os.path.exists(cache_path) else {}
    todo = [c for c in cells if f"{c['q']},{c['r']}" not in cache]
    print(f"  Elevation: {len(todo)} cells to fetch ({len(cells) - len(todo)} cached)")
    for i in range(0, len(todo), 80):
        chunk = todo[i:i + 80]
        url = ("https://api.open-meteo.com/v1/elevation?latitude=" + ",".join(f"{c['lat']:.5f}" for c in chunk)
               + "&longitude=" + ",".join(f"{c['lon']:.5f}" for c in chunk))
        for attempt in range(6):
            r = requests.get(url, timeout=60)
            if r.status_code == 429:
                time.sleep(30)
                continue
            r.raise_for_status()
            for c, e in zip(chunk, r.json()["elevation"]):
                cache[f"{c['q']},{c['r']}"] = e
            break
        write_json(cache_path, cache)
        time.sleep(1.5)
    return cache


def main(cfg_path):
    cfg = load_config(cfg_path)
    raw = data_dir(cfg, "raw")
    R = cfg.get("hex_radius_m", 250)
    proj = Projection(cfg["bbox"])
    print(f"Building grid for {cfg['name']} (hexagon radius {R} m)")

    boundary = polygons_from_geojson(read_json(os.path.join(raw, "boundary.geojson")), proj)
    water = []
    for e in read_json(os.path.join(raw, "osm_water.json")):
        if e["type"] == "way" and e.get("geometry") and len(e["geometry"]) > 3:
            g = e["geometry"]
            if (g[0]["lat"], g[0]["lon"]) == (g[-1]["lat"], g[-1]["lon"]):
                water.append([proj.xy(p["lat"], p["lon"]) for p in g])

    xs = [p[0] for poly in boundary for p in poly[0]]
    ys = [p[1] for poly in boundary for p in poly[0]]
    cells = {}
    for r in range(int(min(ys) / (1.5 * R)) - 1, int(max(ys) / (1.5 * R)) + 2):
        for q in range(int(min(xs) / (math.sqrt(3) * R) - r / 2) - 2, int(max(xs) / (math.sqrt(3) * R) - r / 2) + 3):
            x, y = hex_center(q, r, R)
            if not in_polygons(x, y, boundary) or any(point_in_ring(x, y, w) for w in water):
                continue
            lat, lon = proj.latlon(x, y)
            cells[(q, r)] = dict(q=q, r=r, x=x, y=y, lat=lat, lon=lon, buildings=0, res=0.0)
    print(f"  {len(cells)} hexagons inside the boundary")

    major, cyc = [], []
    for e in read_json(os.path.join(raw, "osm_ways.json")):
        t, pts = e.get("tags", {}), [proj.xy(p["lat"], p["lon"]) for p in e.get("geometry", [])]
        hw = t.get("highway")
        for a, b in zip(pts, pts[1:]):
            if hw in MAJOR_TYPES:
                major.append((a, b))
            if is_cycleway(t):
                cyc.append((a, b))
            if hw in RES_TYPES:
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                n = max(1, math.ceil(length / 50))
                for k in range(n):
                    mx = a[0] + (b[0] - a[0]) * (k + 0.5) / n
                    my = a[1] + (b[1] - a[1]) * (k + 0.5) / n
                    c = cells.get(hex_of(mx, my, R))
                    if c:
                        c["res"] += length / n
    for e in read_json(os.path.join(raw, "osm_buildings.json")):
        c = e.get("center")
        if c:
            cell = cells.get(hex_of(*proj.xy(c["lat"], c["lon"]), R))
            if cell:
                cell["buildings"] += 1

    bus, svc, shop, places = [], [], [], []
    for e in read_json(os.path.join(raw, "osm_points.json")):
        t = e.get("tags", {})
        lat = e.get("lat", e.get("center", {}).get("lat"))
        lon = e.get("lon", e.get("center", {}).get("lon"))
        if lat is None:
            continue
        p = proj.xy(lat, lon)
        if t.get("highway") == "bus_stop" or t.get("public_transport") == "platform":
            bus.append(p)
        elif "shop" in t:
            shop.append(p)
            if t["shop"] in ("supermarket", "mall"):
                svc.append(p)
        elif t.get("amenity") in SERVICE_TYPES:
            svc.append(p)
        elif "place" in t and t.get("name") and in_polygons(p[0], p[1], boundary):
            places.append((t["name"], p))

    stations = [proj.xy(float(s["lat"]), float(s["lon"])) for s in read_csv(os.path.join(data_dir(cfg), "stations.csv"))]
    print(f"  {len(bus)} bus stops, {len(svc)} services, {len(shop)} shops, {len(places)} places, {len(stations)} stations")

    # Population: each zone's census total spread by buildings (60%) and residential street length (40%).
    zones = cfg.get("population", {}).get("zones") or [{"name": cfg["name"], "population": cfg["population"]["total"], "places": []}]
    place_zone = {p: z["name"] for z in zones for p in z.get("places", [])}
    default_zone = cfg.get("population", {}).get("default_zone", zones[0]["name"])
    for c in cells.values():
        c["place"] = min(places, key=lambda p: (p[1][0] - c["x"]) ** 2 + (p[1][1] - c["y"]) ** 2)[0] if places else ""
        c["zone"] = place_zone.get(c["place"], default_zone)
    area_km2 = 1.5 * math.sqrt(3) * R * R / 1e6
    for z in zones:
        zc = [c for c in cells.values() if c["zone"] == z["name"]]
        sb = sum(c["buildings"] for c in zc) or 1
        sr = sum(c["res"] for c in zc) or 1
        for c in zc:
            c["pop"] = z["population"] * (0.6 * c["buildings"] / sb + 0.4 * c["res"] / sr)
    for c in cells.values():
        c["density"] = c["pop"] / area_km2

    pop_idx = PointIndex([(c["x"], c["y"], c["pop"]) for c in cells.values()])
    bus_idx, svc_idx, shop_idx, st_idx = PointIndex(bus), PointIndex(svc), PointIndex(shop), PointIndex(stations)
    maj_idx, cyc_idx = SegmentIndex(major), SegmentIndex(cyc)
    for c in cells.values():
        x, y = c["x"], c["y"]
        c["pop600"] = sum(p[2] for p in pop_idx.within(x, y, 600))
        c["services600"] = len(svc_idx.within(x, y, 600))
        c["shops600"] = len(shop_idx.within(x, y, 600))
        c["bus_stops400"] = len(bus_idx.within(x, y, 400))
        c["bus_stop_m"] = bus_idx.nearest(x, y)
        c["major_road_m"] = maj_idx.nearest(x, y)
        c["cycleway_m"] = cyc_idx.nearest(x, y)
        c["station_m"] = st_idx.nearest(x, y, cap=20000) if stations else 20000

    urban = [c for c in cells.values() if c["density"] >= 300 or c["services600"] + c["shops600"] >= 3]
    print(f"  {len(urban)} populated hexagons kept")

    if cfg.get("elevation", True):
        elev = fetch_elevation(urban, os.path.join(raw, "elevation.json"))
        for c in urban:
            c["elev_m"] = elev.get(f"{c['q']},{c['r']}")
        by_key = {(c["q"], c["r"]): c for c in urban}
        step = math.sqrt(3) * R
        for c in urban:
            s = 0.0
            for dq, dr in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)):
                n = by_key.get((c["q"] + dq, c["r"] + dr))
                if n and n.get("elev_m") is not None and c.get("elev_m") is not None:
                    s = max(s, abs(n["elev_m"] - c["elev_m"]) / step * 100)
            c["slope_pct"] = s
    out = []
    for c in urban:
        row = dict(c, res_street_m=c["res"])
        for k in ("pop", "density", "pop600", "res_street_m", "bus_stop_m", "major_road_m", "cycleway_m", "station_m"):
            row[k] = round(row[k])
        row["lat"], row["lon"] = round(c["lat"], 6), round(c["lon"], 6)
        row["slope_pct"] = round(c.get("slope_pct", 0.0), 1)
        out.append(row)
    path = os.path.join(data_dir(cfg), "hex_features.csv")
    write_csv(path, out, FIELDS)
    print(f"Wrote {path}. Next: python src/score_sites.py {cfg_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/build_grid.py config/<city>.json")
    main(sys.argv[1])
