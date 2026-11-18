"""Turn pairwise judgments (Saaty 1-9 scale) into criterion weights.

Usage:
    python src/ahp.py config/marica.json

Reads the "pairwise" block of the config, prints the weights and the
consistency ratio (CR). A CR under 0.10 is usually considered acceptable.
Copy the printed weights into the "weights" block if you change judgments.
"""
import sys

from common import load_config

RANDOM_INDEX = {1: 0, 2: 0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


def ahp(criteria, judgments):
    n = len(criteria)
    idx = {c: i for i, c in enumerate(criteria)}
    a = [[1.0] * n for _ in range(n)]
    for left, right, value in judgments:
        i, j = idx[left], idx[right]
        a[i][j], a[j][i] = float(value), 1.0 / float(value)
    w = [1.0 / n] * n
    for _ in range(200):  # power iteration for the principal eigenvector
        nw = [sum(a[i][j] * w[j] for j in range(n)) for i in range(n)]
        s = sum(nw)
        nw = [x / s for x in nw]
        if max(abs(x - y) for x, y in zip(nw, w)) < 1e-12:
            w = nw
            break
        w = nw
    lam = sum(sum(a[i][j] * w[j] for j in range(n)) / w[i] for i in range(n)) / n
    ci = (lam - n) / (n - 1) if n > 2 else 0.0
    cr = ci / RANDOM_INDEX[n] if RANDOM_INDEX.get(n) else 0.0
    return dict(zip(criteria, w)), cr


def main(cfg_path):
    cfg = load_config(cfg_path)
    pw = cfg["pairwise"]
    weights, cr = ahp(pw["criteria"], pw["judgments"])
    print("Weights:")
    for k, v in weights.items():
        print(f"  {k:<10} {v:.3f}")
    print(f"Consistency ratio: {cr:.3f} ({'acceptable' if cr < 0.10 else 'revise the judgments'})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/ahp.py config/<city>.json")
    main(sys.argv[1])
