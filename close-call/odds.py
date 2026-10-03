"""Close Call (close-1) odds check. Downloads the referee's public price room, then reports:
- the most one key could have made so far with perfect hindsight, with and without fees;
- the odds that the best of K of our keys, trading fee-free on random 30-minute long/short
  sequences from now to the lock, beats a given score (default: today's leader).

    uv run --python 3.12 --with numpy odds.py [--bar 1424] [--keys 100 250 400]
"""
import argparse, json, urllib.request
from pathlib import Path
import numpy as np

EXPORT = "https://technocore.chat/r/d-close1-price/export"
LOCK_SWEEP, WEEKEND_START = 2556, "2026-10-02T20:00"   # US cash close Friday; xyz:NVDA barely moves after it


def prices(path: Path):
    if not path.exists():
        path.write_bytes(urllib.request.urlopen(EXPORT, timeout=120).read())
    rows = [json.loads(json.loads(line)["text"]) for line in path.open()]
    rows = [r for r in rows if r.get("t") == "price"]
    return np.array([float(r["ref"]["px"]) for r in rows]), rows[-1]


def perfect_hindsight(path, fee):
    """Best equity multiple from a chain of full-size long/short holds, fee on each open and close, none at S."""
    n, best = len(path), np.zeros(len(path))
    best[0] = 1.0
    for b in range(1, n):
        pa, pb, e = path[:b], path[b], best[:b]
        close_fee = 0.0 if b == n - 1 else fee
        long_ = e * pb * (1 - close_fee) / ((1 + fee) * pa)
        short = e * (2 * pa - pb - close_fee * pb) / ((1 + fee) * pa)
        best[b] = max(best[b - 1], long_.max(), short.max())
    return best[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bar", type=float, default=1424.0, help="score to beat, POLF")
    ap.add_argument("--keys", type=int, nargs="+", default=[100, 250, 400])
    ap.add_argument("--data", type=Path, default=Path(__file__).with_name("price.jsonl"))
    args = ap.parse_args()

    P, last = prices(args.data)
    print(f"last sweep {last['n']}  ref {last['ref']['px']}  season range {P.min():.2f}-{P.max():.2f}")
    print(f"perfect hindsight so far: with 1% fees {100 * (perfect_hindsight(P, 0.01) - 1):+.1f}%, "
          f"fee-free {100 * (perfect_hindsight(P, 0.0) - 1):+.1f}%")

    # bootstrap the rest of the season from realised 5-minute returns, weekday and weekend separately
    r = np.diff(np.log(P))
    hours = np.arange(1, len(P)) * 5 / 60                      # from Fri 25 Sep 12:05 UTC
    weekend = (hours > 8) & (hours <= 68)
    left = LOCK_SWEEP - last["n"]
    now = np.datetime64(last["ref"]["time"][:16])
    weekday_left = max(0, min(left, int((np.datetime64(WEEKEND_START) - now) / np.timedelta64(5, "m"))))
    rng = np.random.default_rng(3)
    for k in args.keys:
        for scale in (1, 2, 3):
            best = []
            for _ in range(1000):
                rr = np.concatenate([scale * rng.choice(r[~weekend], weekday_left),
                                     rng.choice(r[weekend], left - weekday_left)])
                blocks = np.add.reduceat(rr, np.arange(0, left, 6))
                signs = rng.choice([-1, 1], size=(k, len(blocks)))
                best.append(10000 * (np.exp(signs @ blocks).max() - 1))
            best = np.array(best)
            print(f"K={k:3d} weekday vol x{scale}: best key p50 {np.percentile(best, 50):+5.0f}  "
                  f"p99 {np.percentile(best, 99):+5.0f}  P(> {args.bar:.0f}) {(best > args.bar).mean():.3f}")


if __name__ == "__main__":
    main()
