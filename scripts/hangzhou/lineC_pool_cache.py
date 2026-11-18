"""Cache per-day C direct anchors (same rule as lineC_direct.direct_directions) for 2019-01-01..25, one day at a time.
Output: outputs/hangzhou/cache/pool_anchors_<date>.npz (e, x, X, minutes, d[1=toward_66]) + pool_cache_summary.csv."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_route_gate as RG
from lineC_direct import direct_directions
import numpy as np, pandas as pd

CACHE = RG.ROOT / "outputs/hangzhou/cache"
DATES = [f"2019-01-{d:02d}" for d in range(1, 26)]


def main():
    RG.DATE = "2019-01-08"
    gate0, trips0, _ = RG.read_tags()
    tracks, membership, _, _, _ = RG.build_topology(gate0)
    corridor = RG.corridor_order(tracks["C"])
    rows = []
    for d in DATES:
        f = CACHE / f"pool_anchors_{d}.npz"
        RG.DATE = d
        gate, trips, exits = RG.read_tags()
        diff = {s for s in gate if s in gate0 and gate[s] != gate0[s]}
        a = direct_directions(trips, corridor, membership)
        np.savez(f, e=a.entry_station.to_numpy(np.int16), x=a.exit_station.to_numpy(np.int16), X=a.exit_seconds.to_numpy(np.int32),
                 minutes=a.minutes.to_numpy(np.float32), d=(a.direction == f"toward_{corridor[-1]}").to_numpy(np.int8))
        rows.append(dict(date=d, c_exit_tags=len(exits), anchors=len(a), share=len(a) / len(exits), gate_code_diffs=len(diff)))
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(CACHE / "pool_cache_summary.csv", index=False)


if __name__ == "__main__":
    main()
