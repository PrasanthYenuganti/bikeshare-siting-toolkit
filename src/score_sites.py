"""Step 3: score every hexagon and choose new station sites in phases.

Usage:
    python src/score_sites.py config/marica.json

Reads data/<city>/hex_features.csv and data/<city>/stations.csv. Writes
outputs/<city>/proposed_sites.csv and outputs/<city>/summary.json.

Scoring: each criterion is converted to a 0-1 percentile rank across all
populated hexagons, combined with the weights in the config, then multiplied
by a terrain factor. Selection is greedy with Bublr-style siting rules:
minimum spacing, no isolated stations (contiguity), optional shares per zone.
"""
import bisect
import math
import os
import sys

from common import Projection, data_dir, load_config, out_dir, read_csv, write_csv, write_json

CRITERIA = {
    "density": lambda h: h["pop600"],
    "services": lambda h: h["services600"],
    "bus": lambda h: h["bus_stops400"] + (2 if h["major_road_m"] < 150 else 0),
    "jobs": lambda h: h["shops600"],
    "cycling": lambda h: -h["cycleway_m"],
}
NUM = ["pop", "density", "pop600", "services600", "shops600", "bus_stops400", "bus_stop_m",
       "major_road_m", "cycleway_m", "station_m", "slope_pct"]


def percentile_ranks(values):
    s = sorted(values)
    n = len(s)
    return [(bisect.bisect_left(s, v) + bisect.bisect_right(s, v)) / 2 / n for v in values]


def prepare(hexes, rules):
    for name, fn in CRITERIA.items():
        for h, v in zip(hexes, percentile_ranks([fn(h) for h in hexes])):
            h["c_" + name] = v
    near, far = rules["gap_min_m"], rules["gap_full_m"]
    for h in hexes:
        h["c_gap"] = 0.0 if h["station_m"] < near else min(1.0, (h["station_m"] - near) / (far - near))
        s = h["slope_pct"]
        h["terrain_factor"] = 1.0 if s <= 5 else (0.85 if s <= 10 else 0.6)


def score(h, weights):
    return h["terrain_factor"] * sum(w * h["c_" + k] for k, w in weights.items())


def coverage(hexes, pts, dist):
    return sum(h["pop"] for h in hexes if pts and min(math.hypot(h["x"] - a, h["y"] - b) for a, b in pts) <= dist)


def select(hexes, weights, n, existing, rules, quota=None, contig=None, contig_by_zone=None, cluster=None, extra=None):
    min_existing = rules["min_from_existing_m"]
    cand = [h for h in hexes if h["station_m"] >= min_existing and h["pop600"] >= rules["min_pop600"]
            and h["pop"] > 0 and (extra is None or extra(h))]
    cand.sort(key=lambda h: -score(h, weights))
    chosen = []
    for h in cand:
        if len(chosen) >= n:
            break
        if quota is not None and sum(1 for c in chosen if c["zone"] == h["zone"]) >= quota.get(h["zone"], 0):
            continue
        pts = [(c["x"], c["y"]) for c in chosen]
        if any(math.hypot(h["x"] - a, h["y"] - b) < rules["spacing_m"] for a, b in pts):
            continue
        if any(math.hypot(h["x"] - a, h["y"] - b) < min_existing for a, b in existing):
            continue
        limit = (contig_by_zone or {}).get(h["zone"], contig)
        if limit and min(math.hypot(h["x"] - a, h["y"] - b) for a, b in list(existing) + pts) > limit:
            continue
        chosen.append(h)
    if cluster:
        chosen = [h for h in chosen if min(math.hypot(h["x"] - a, h["y"] - b)
                  for a, b in [(c["x"], c["y"]) for c in chosen if c is not h] + list(existing)) <= cluster]
    return chosen


def gain(hexes, existing, sel):
    pts = list(existing) + [(h["x"], h["y"]) for h in sel]
    return {"stations": len(sel),
            "added_within_300m": round(coverage(hexes, pts, 300) - coverage(hexes, existing, 300)),
            "added_within_500m": round(coverage(hexes, pts, 500) - coverage(hexes, existing, 500)),
            "avg_bus_stops_400m": round(sum(h["bus_stops400"] for h in sel) / max(1, len(sel)), 1),
            "places_reached": sorted({h["place"] for h in sel})}


def main(cfg_path):
    cfg = load_config(cfg_path)
    rules, weights = cfg["rules"], cfg["weights"]
    proj = Projection(cfg["bbox"])
    hexes = read_csv(os.path.join(data_dir(cfg), "hex_features.csv"))
    for h in hexes:
        for k in NUM:
            h[k] = float(h[k] or 0)
        h["x"], h["y"] = proj.xy(float(h["lat"]), float(h["lon"]))
    stations = [proj.xy(float(s["lat"]), float(s["lon"])) for s in read_csv(os.path.join(data_dir(cfg), "stations.csv"))]
    prepare(hexes, rules)
    total = sum(h["pop"] for h in hexes)
    print(f"Scoring {len(hexes)} hexagons for {cfg['name']}; {len(stations)} existing stations")

    existing, plan, phase_stats = list(stations), [], []
    for ph in cfg["phases"]:
        sel = select(hexes, weights, ph["n"], existing, rules, quota=ph.get("quota"), contig=ph.get("contig_m"),
                     contig_by_zone=ph.get("contig_by_zone"), cluster=ph.get("cluster_m"))
        phase_stats.append(dict(phase=ph["name"], **gain(hexes, existing, sel)))
        plan += [(ph["name"], h) for h in sel]
        existing += [(h["x"], h["y"]) for h in sel]
        print(f"  Phase {ph['name']}: {len(sel)} sites, +{phase_stats[-1]['added_within_500m']:,} residents within 500 m")

    scenarios = {}
    for name, sc in cfg.get("scenarios", {}).items():
        extra = (lambda h: h["bus_stops400"] >= 2 or h["major_road_m"] < 100) if sc.get("require_transit") else None
        r2 = dict(rules, spacing_m=sc.get("spacing_m", rules["spacing_m"]))
        sel = select(hexes, sc["weights"], sc.get("n_candidates", sc["n"]), stations, r2, contig=sc.get("contig_m"),
                     cluster=sc.get("cluster_m"), extra=extra)[:sc["n"]]
        scenarios[name] = dict(description=sc["description"], **gain(hexes, stations, sel))

    zones = sorted({h["zone"] for h in hexes})
    by_zone = {}
    for z in zones:
        zh = [h for h in hexes if h["zone"] == z]
        p = sum(h["pop"] for h in zh) or 1
        by_zone[z] = {"population": round(p), "new_stations": sum(1 for _, h in plan if h["zone"] == z),
                      "now_300m_pct": round(100 * coverage(zh, stations, 300) / p, 1),
                      "now_500m_pct": round(100 * coverage(zh, stations, 500) / p, 1),
                      "plan_300m_pct": round(100 * coverage(zh, existing, 300) / p, 1),
                      "plan_500m_pct": round(100 * coverage(zh, existing, 500) / p, 1)}

    rows = []
    for i, (ph, h) in enumerate(plan, 1):
        rows.append({"id": f"P{ph}-{i:02d}", "phase": ph, "zone": h["zone"], "place": h["place"],
                     "lat": h["lat"], "lon": h["lon"], "score": round(score(h, weights), 3),
                     "residents_600m": round(h["pop600"]), "services_600m": int(h["services600"]),
                     "shops_600m": int(h["shops600"]), "bus_stops_400m": int(h["bus_stops400"]),
                     "nearest_bus_stop_m": round(h["bus_stop_m"]), "nearest_major_road_m": round(h["major_road_m"]),
                     "nearest_cycleway_m": round(h["cycleway_m"]), "nearest_station_today_m": round(h["station_m"]),
                     "terrain_slope_pct": h["slope_pct"]})
    out = out_dir(cfg)
    write_csv(os.path.join(out, "proposed_sites.csv"), rows, list(rows[0].keys()) if rows else ["id"])
    summary = {"city": cfg["name"], "population_modelled": round(total),
               "existing_stations": len(stations),
               "coverage_now": {"within_300m_pct": round(100 * coverage(hexes, stations, 300) / total, 1),
                                "within_500m_pct": round(100 * coverage(hexes, stations, 500) / total, 1)},
               "coverage_with_plan": {"within_300m_pct": round(100 * coverage(hexes, existing, 300) / total, 1),
                                      "within_500m_pct": round(100 * coverage(hexes, existing, 500) / total, 1)},
               "phases": phase_stats, "zones": by_zone, "scenarios": scenarios}
    write_json(os.path.join(out, "summary.json"), summary)
    print(f"  Coverage within 500 m: {summary['coverage_now']['within_500m_pct']}% now, "
          f"{summary['coverage_with_plan']['within_500m_pct']}% with the plan")
    print(f"Wrote {out}/proposed_sites.csv and summary.json")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/score_sites.py config/<city>.json")
    main(sys.argv[1])
