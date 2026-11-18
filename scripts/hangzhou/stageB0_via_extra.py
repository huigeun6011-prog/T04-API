"""Stage B0 extra (post-hoc, exploratory, nothing tuned): for each line pair, is the direct single-hub fit beaten by going via the third line?
Uses the hubs already fitted by stageB0_hubs.py (hubs_B0.json) and one constant W per route (median residual). 2019-01-08 only."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[2]
sys.argv = ["x"]
src = (ROOT / "scripts/hangzhou/stageB0_hubs.py").read_text(encoding="utf-8").split("rng = np.random.default_rng(20190108)")[0]
ns = {"__file__": str(ROOT / "scripts/hangzhou/stageB0_hubs.py")}; exec(compile(src, "hubs_head", "exec"), ns)
cfun, side, tr = ns["cfun"], ns["side"], ns["tr"]
hub = json.load(open(ROOT / "outputs/hangzhou/cache/hubs_B0.json"))
cross = tr[tr.entry_line != tr.exit_line]
h = {k: v["hubs"][0] for k, v in hub.items()}      # AB:(posA,posB), AC:(posA,posC), BC:(posB,posC)
out = []
def leg(L, a, b): return cfun(L, np.abs(np.asarray(a) - np.asarray(b)))
for X, Y, Z in (("A", "B", "C"), ("A", "C", "B"), ("B", "C", "A")):
    d = side(cross, X, Y); m = d.minutes.to_numpy(); n = len(d); pX, pY = d.pX.to_numpy(), d.pY.to_numpy()
    k = X + Y
    direct = m - leg(X, pX, h[k][0]) - leg(Y, pY, h[k][1]); wd = np.median(direct)
    # via Z: X-Z hub then Z-Y hub
    xz = h[X + Z] if X + Z in h else h[Z + X][::-1]; zy = h[Z + Y] if Z + Y in h else h[Y + Z][::-1]
    via = m - leg(X, pX, xz[0]) - leg(Z, xz[1], zy[0]) - leg(Y, pY, zy[1]); wv = np.median(via)
    ad, av = np.abs(direct - wd), np.abs(via - wv)
    out.append(dict(pair=k, via=Z, n=n, direct_1hub_mean_abs=round(float(ad.mean()), 3), direct_W=round(float(wd), 2), via_mean_abs=round(float(av.mean()), 3), via_W=round(float(wv), 2),
                    share_via_better_by_3=round(float((av + 3 < ad).mean()), 3), share_direct_better_by_3=round(float((ad + 3 < av).mean()), 3), via_leg_stations=int(abs(xz[1] - zy[0]))))
o = pd.DataFrame(out); o.to_csv(ROOT / "outputs/hangzhou/stageB0/via_third_line_all.csv", index=False); print(o.to_string())
hp = pd.read_csv(ROOT / "outputs/hangzhou/stageB0/hubs_per_pair.csv"); w = {"AB": 128509, "AC": 68030, "BC": 199855}
for k in (1, 2, 3):
    s = hp[hp.n_hubs == k].set_index("pair"); print(k, "hubs: weighted splittable share", round(sum(s.splittable_share[p] * w[p] for p in w) / sum(w.values()), 3), "within5", round(sum(s.share_within_5[p] * w[p] for p in w) / sum(w.values()), 3))
