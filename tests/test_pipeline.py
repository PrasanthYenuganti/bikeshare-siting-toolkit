"""Offline test: builds a small synthetic city and runs steps 2 and 3.

Run from the repository folder:
    python tests/test_pipeline.py
No internet connection is needed.
"""
import os
import random
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import ahp  # noqa: E402
import build_grid  # noqa: E402
import score_sites  # noqa: E402
from common import hex_center, hex_of, read_csv, read_json, write_json  # noqa: E402

SLUG = "_testcity"


def make_city():
    random.seed(7)
    s, w, n, e = -23.00, -43.00, -22.94, -42.92
    cfg = {
        "name": "Test City", "bbox": [s, w, n, e], "boundary_url": "", "hex_radius_m": 250, "elevation": False,
        "population": {"zones": [{"name": "West", "population": 30000, "places": ["Oeste"]},
                                 {"name": "East", "population": 20000, "places": ["Leste"]}], "default_zone": "West"},
        "weights": {"density": 0.222, "services": 0.222, "bus": 0.222, "jobs": 0.111, "gap": 0.111, "cycling": 0.111},
        "rules": {"spacing_m": 450, "min_from_existing_m": 350, "min_pop600": 200, "gap_min_m": 350, "gap_full_m": 1500},
        "phases": [{"name": "1", "n": 4, "contig_m": 1500}, {"name": "2", "n": 4, "contig_m": 2000, "quota": {"West": 2, "East": 2}}],
        "scenarios": {"B": {"description": "transit", "n": 3, "require_transit": True,
                            "weights": {"bus": 0.5, "density": 0.5}}},
        "pairwise": {"criteria": ["a", "b", "c"], "judgments": [["a", "b", 2], ["a", "c", 4], ["b", "c", 2]]},
    }
    cfg_path = os.path.join(ROOT, "config", SLUG + ".json")
    write_json(cfg_path, cfg)
    raw = os.path.join(ROOT, "data", SLUG, "raw")
    os.makedirs(raw, exist_ok=True)
    ring = [[w + 0.005, s + 0.005], [e - 0.005, s + 0.005], [e - 0.005, n - 0.005], [w + 0.005, n - 0.005], [w + 0.005, s + 0.005]]
    write_json(os.path.join(raw, "boundary.geojson"),
               {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}}]})
    ways = []
    for i in range(12):
        lat = s + 0.008 + i * 0.004
        ways.append({"type": "way", "tags": {"highway": "residential"},
                     "geometry": [{"lat": lat, "lon": w + 0.008}, {"lat": lat, "lon": e - 0.008}]})
    ways.append({"type": "way", "tags": {"highway": "primary"}, "geometry": [{"lat": s + 0.03, "lon": w + 0.006}, {"lat": s + 0.03, "lon": e - 0.006}]})
    ways.append({"type": "way", "tags": {"highway": "cycleway"}, "geometry": [{"lat": s + 0.01, "lon": w + 0.02}, {"lat": n - 0.01, "lon": w + 0.02}]})
    write_json(os.path.join(raw, "osm_ways.json"), ways)
    write_json(os.path.join(raw, "osm_buildings.json"),
               [{"type": "way", "center": {"lat": random.uniform(s + 0.006, n - 0.006), "lon": random.uniform(w + 0.006, e - 0.006)}} for _ in range(3000)])
    pts = [{"type": "node", "lat": s + 0.03, "lon": w + 0.01 + k * 0.006, "tags": {"highway": "bus_stop"}} for k in range(12)]
    pts += [{"type": "node", "lat": random.uniform(s + 0.01, n - 0.01), "lon": random.uniform(w + 0.01, e - 0.01), "tags": {"amenity": "school"}} for _ in range(30)]
    pts += [{"type": "node", "lat": random.uniform(s + 0.01, n - 0.01), "lon": random.uniform(w + 0.01, e - 0.01), "tags": {"shop": "bakery"}} for _ in range(60)]
    pts += [{"type": "node", "lat": s + 0.03, "lon": w + 0.02, "tags": {"place": "suburb", "name": "Oeste"}},
            {"type": "node", "lat": s + 0.03, "lon": e - 0.02, "tags": {"place": "suburb", "name": "Leste"}}]
    write_json(os.path.join(raw, "osm_points.json"), pts)
    write_json(os.path.join(raw, "osm_water.json"), [])
    with open(os.path.join(ROOT, "data", SLUG, "stations.csv"), "w", encoding="utf-8") as f:
        f.write("station_id,name,lat,lon,source\nS1,,-22.97,-42.97,test\nS2,,-22.97,-42.96,test\n")
    return cfg_path


def main():
    for q, r in [(0, 0), (3, -2), (-5, 7)]:
        x, y = hex_center(q, r, 250)
        assert hex_of(x, y, 250) == (q, r), "hexagon round trip failed"
    weights, cr = ahp.ahp(["a", "b", "c"], [["a", "b", 2], ["a", "c", 4], ["b", "c", 2]])
    assert abs(sum(weights.values()) - 1) < 1e-9 and cr < 0.01, "AHP check failed"

    cfg_path = make_city()
    try:
        build_grid.main(cfg_path)
        hexes = read_csv(os.path.join(ROOT, "data", SLUG, "hex_features.csv"))
        assert len(hexes) > 50, "too few hexagons"
        assert abs(sum(float(h["pop"]) for h in hexes) - 50000) < 500, "population does not add up"
        score_sites.main(cfg_path)
        summ = read_json(os.path.join(ROOT, "outputs", SLUG, "summary.json"))
        assert summ["coverage_with_plan"]["within_500m_pct"] > summ["coverage_now"]["within_500m_pct"], "plan adds no coverage"
        assert sum(p["stations"] for p in summ["phases"]) == 8, "wrong number of sites"
        print("\nAll checks passed.")
    finally:
        os.remove(cfg_path)
        shutil.rmtree(os.path.join(ROOT, "data", SLUG), ignore_errors=True)
        shutil.rmtree(os.path.join(ROOT, "outputs", SLUG), ignore_errors=True)


if __name__ == "__main__":
    main()
