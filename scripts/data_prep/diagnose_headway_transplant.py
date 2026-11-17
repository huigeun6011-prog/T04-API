"""Step 1b: does uniform headway lower loads by itself (same p,q) or only through the optimizer re-fit?
Baseline-fitted p,q are evaluated with flat-headway boarding (no refit), then compared with the refit headway."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt, gt_arrival_curve as ac
from experiment_queue_model import CASES
OUT = gt.ROOT / "outputs/diagnostics/arrival_curve"
rows = []
def st(f):
    t = f.loc[f.is_destination == 1, "raw_load"]
    return dict(term_mse=float((t ** 2).mean()), neg_mse=float((np.minimum(f.raw_load, 0) ** 2).mean()), load_mean=float(f.load.mean()),
                load_p99=float(f.load.quantile(.99)), peak_hour_load=float(f[f.hour.isin([8, 18])].load.mean()))
for date in CASES:
    fb, ab = ac.solve_day(date, "baseline", epochs=1000)
    ft, _ = ac.solve_day(date, "flat", fixed_pq=(ab["p_fit"], ab["q_fit"]))
    fh, ah = ac.solve_day(date, "flat", epochs=1000)
    for name, f in (("baseline_fit", fb), ("baseline_pq_with_headway_boarding", ft), ("headway_refit", fh)):
        rows.append(dict(date=date, arm=name, **st(f)))
    rows.append(dict(date=date, arm="mean_abs_p_diff_baseline_vs_headway_refit", term_mse=float(np.abs(ab["p_fit"] - ah["p_fit"])[1:-1].mean())))
df = pd.DataFrame(rows); df.to_csv(OUT / "diag_headway_transplant.csv", index=False)
print(df.round(2).to_string())
