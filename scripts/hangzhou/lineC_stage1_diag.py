"""Stage 1 diagnosis only (after the gate failed; no gate/setting changed): where does the B-C fit lose trips? 2019-01-08."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from lineC_common import *
tr = pd.read_pickle(CACHE / "trips_2019-01-08.pkl")
a = tr[(tr.entry_line == "B") & (tr.exit_line == "C")].assign(bs=lambda x: x.entry_st, cs=lambda x: x.exit_st, hour=lambda x: (x.p_t // 3600))
b = tr[(tr.entry_line == "C") & (tr.exit_line == "B")].assign(bs=lambda x: x.exit_st, cs=lambda x: x.entry_st, hour=lambda x: (x.p_t // 3600))
d = pd.concat([a, b]); m = d.minutes.to_numpy()
def fit(hb, hc, branch=True):
    r = m - cfun("B", b_dist(d.bs.to_numpy(), np.full(len(d), hb), branch)) - cfun("C", np.abs(d.cs.map(POS["C"]).to_numpy() - POS["C"][hc])); W = np.median(r); return r - W, W
rows = []
for hb in (9, 10, 11):
    for hc in range(46, 53):
        r, W = fit(hb, hc); rows.append(dict(B=hb, C=hc, W=round(W, 2), within5=round(float((np.abs(r) <= 5).mean()), 4), mean_abs=round(float(np.abs(r).mean()), 3)))
scan = pd.DataFrame(rows).sort_values("mean_abs"); scan.to_csv(OUT / "stage1_diag_hub_scan.csv", index=False); print(scan.head(8).to_string())
r, W = fit(10, 51)
d = d.assign(res=r, branch=d.bs >= 28, cside=np.where(d.cs.map(POS["C"]) < POS["C"][51], "C_below", "C_above"), bside=np.where(d.bs < 10, "B<10", np.where(d.bs <= 27, "B>=10 trunk", "branch")))
out = d.groupby(["bside", "cside"]).res.agg(n="size", median="median", p25=lambda x: x.quantile(.25), p75=lambda x: x.quantile(.75), within5=lambda x: (x.abs() <= 5).mean()).round(3)
print(out); out.to_csv(OUT / "stage1_diag_by_side.csv")
h = d.groupby(pd.cut(d.hour, [0, 6, 9, 12, 16, 19, 24])).res.agg(n="size", median="median", within5=lambda x: (x.abs() <= 5).mean()).round(3); print(h); h.to_csv(OUT / "stage1_diag_by_hour.csv")
print("residual quantiles", np.quantile(r, [.05, .25, .5, .75, .95]).round(1))
