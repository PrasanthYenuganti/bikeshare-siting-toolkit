"""Shared helpers: configuration, local projection, hexagon grid and geometry.

All distances are in metres on a local equirectangular projection centred on
the study area. That is accurate to well under 1% across a single city.
"""
import csv
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQRT3 = math.sqrt(3)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_slug"] = os.path.splitext(os.path.basename(path))[0]
    return cfg


def data_dir(cfg, *parts):
    d = os.path.join(ROOT, "data", cfg["_slug"], *parts)
    os.makedirs(d, exist_ok=True)
    return d


def out_dir(cfg):
    d = os.path.join(ROOT, "outputs", cfg["_slug"])
    os.makedirs(d, exist_ok=True)
    return d


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


class Projection:
    """Local metres <-> lat/lon around the centre of a bounding box."""

    def __init__(self, bbox):
        south, west, north, east = bbox
        self.lat0 = (south + north) / 2
        self.lon0 = (west + east) / 2
        self.kx = 111320 * math.cos(math.radians(self.lat0))
        self.ky = 110574 + 1110 * math.sin(math.radians(self.lat0)) ** 2

    def xy(self, lat, lon):
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def latlon(self, x, y):
        return (self.lat0 + y / self.ky, self.lon0 + x / self.kx)


def hex_center(q, r, radius):
    """Centre of a pointy-top axial hexagon (q, r)."""
    return (radius * SQRT3 * (q + r / 2), radius * 1.5 * r)


def hex_of(x, y, radius):
    """Axial coordinates (q, r) of the hexagon containing point (x, y)."""
    q = (SQRT3 / 3 * x - y / 3) / radius
    r = (2 / 3 * y) / radius
    s = -q - r
    rq, rr, rs = round(q), round(r), round(s)
    dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
    if dq > dr and dq > ds:
        rq = -rr - rs
    elif dr > ds:
        rr = -rq - rs
    return (rq, rr)


def point_in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def polygons_from_geojson(gj, proj):
    """Return a list of polygons [[outer, hole, ...], ...] in local metres."""
    feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    polys = []
    for f in feats:
        g = f.get("geometry", f)
        coords = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in coords:
            polys.append([[proj.xy(lat, lon) for lon, lat in ring] for ring in poly])
    return polys


def in_polygons(x, y, polys):
    for poly in polys:
        if point_in_ring(x, y, poly[0]) and not any(point_in_ring(x, y, h) for h in poly[1:]):
            return True
    return False


def seg_dist(px, py, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / l2))
    return math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))


class PointIndex:
    """Simple grid bucket index for fast radius queries on many points."""

    def __init__(self, pts, cell=500.0):
        self.cell = cell
        self.b = {}
        for p in pts:
            k = (int(p[0] // cell), int(p[1] // cell))
            self.b.setdefault(k, []).append(p)

    def within(self, x, y, r):
        c = self.cell
        out = []
        for i in range(int((x - r) // c), int((x + r) // c) + 1):
            for j in range(int((y - r) // c), int((y + r) // c) + 1):
                for p in self.b.get((i, j), ()):
                    if math.hypot(p[0] - x, p[1] - y) <= r:
                        out.append(p)
        return out

    def nearest(self, x, y, cap=5000.0):
        r = self.cell
        while r <= cap * 2:
            pts = self.within(x, y, r)
            if pts:
                return min(math.hypot(p[0] - x, p[1] - y) for p in pts)
            r *= 2
        return cap


class SegmentIndex:
    """Grid bucket index of line segments for nearest-distance queries."""

    def __init__(self, segs, cell=500.0):
        self.cell = cell
        self.b = {}
        for s in segs:
            (x1, y1), (x2, y2) = s
            for i in range(int(min(x1, x2) // cell), int(max(x1, x2) // cell) + 1):
                for j in range(int(min(y1, y2) // cell), int(max(y1, y2) // cell) + 1):
                    self.b.setdefault((i, j), []).append(s)

    def nearest(self, x, y, cap=3000.0):
        c = self.cell
        best = cap
        rings = int(cap // c) + 1
        for ring in range(rings + 1):
            if ring * c - c > best:
                break
            ci, cj = int(x // c), int(y // c)
            for i in range(ci - ring, ci + ring + 1):
                for j in range(cj - ring, cj + ring + 1):
                    if max(abs(i - ci), abs(j - cj)) != ring:
                        continue
                    for s in self.b.get((i, j), ()):
                        d = seg_dist(x, y, s[0], s[1])
                        if d < best:
                            best = d
        return best
