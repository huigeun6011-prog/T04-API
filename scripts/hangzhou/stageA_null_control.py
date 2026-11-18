"""Control for stageA_peaks: replace each station's 10-16h exits by a Poisson process with the same slowly varying rate
(histogram smoothed with sigma=600 s), apply the SAME declared detector/classes. Shows how often 'clear' appears without arrival structure."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import importlib.util, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy.ndimage import gaussian_filter1d
ROOT = Path(__file__).resolve().parents[2]
src = (ROOT / "scripts/hangzhou/stageA_peaks.py").read_text(encoding="utf-8").split("rows, W1, W2")[0]
ns = {"__file__": str(ROOT / "scripts/hangzhou/stageA_peaks.py")}; exec(compile(src, "peaks_head", "exec"), ns)
rng = np.random.default_rng(0); lo, hi = 10 * 3600, 16 * 3600; rows = []
for (line, st), g in ns["ex"].groupby(["lineID", "stationID"]):
    t = g.t.to_numpy(); h = np.bincount(t[(t >= lo) & (t < hi)] - lo, minlength=hi - lo).astype(float)
    rate = gaussian_filter1d(h, 600, mode="nearest")
    sim = np.repeat(np.arange(hi - lo), rng.poisson(rate)) + lo
    a = ns["analyse"](sim, lo, hi); a.update(lineID=line, stationID=st); rows.append(a)
d = pd.DataFrame(rows); d.to_csv(ROOT / "outputs/hangzhou/stageA/null_control_poisson.csv", index=False)
print(d.cls.value_counts().to_dict(), d.groupby("cls")[["explained", "lift"]].median().round(2).to_dict())
