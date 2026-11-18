"""Zone statistics peek (no verdicts): per direction x band, median exits per train per day, E3-informative segment share, share of anchors."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_pos2 as Q, numpy as np, pandas as pd
c = Q.setup()
N = Q.Ncounts(c, np.ones(c["ps"].n, bool), c["posx"])
nd = len(c["days"])
rows = []
for di in (0, 1):
    for b in range(5):
        ix = np.flatnonzero(c["bidx"][di] == b)
        per_train_day = N[di][:, ix, :].sum(2)       # day x train
        tot = N[di].sum(0)[ix]
        typ = np.column_stack([tot[:, a:z].sum(1) for a, z in Q.SEG]).mean(0)
        rows.append(dict(direction=c["dnames"][di], band=Q.BANDS[b][0], trains=len(ix), median_exits_per_train_per_day=float(np.median(per_train_day)),
                         informative_seg_share=float((typ >= 100).mean()), exits_share=float(N[di][:, ix, :].sum() / sum(N[d_].sum() for d_ in (0, 1)))))
print(pd.DataFrame(rows).round(3).to_string())
