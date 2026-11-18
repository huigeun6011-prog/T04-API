"""Stage A items 3,4,5: arrival-peak visibility per (line, station), 2019-01-08 only, exits from the stageA_pairing cache.
Run after stageA_pairing.py:  .venv/Scripts/python.exe -I scripts/hangzhou/stageA_peaks.py

DECLARED BEFORE LOOKING AT ANY RESULT (not to be changed afterwards):
  detection: 1-second exit histogram, gaussian_filter1d(sigma=10 s), find_peaks(distance=45 s, height=2.5*mean of the smoothed window).
  window: 10:00-16:00 (all stations); 07:00-09:00 for the 10 busiest stations (by exits in 10-16h). hours = window length in h.
  explained = share of window exits within +/-45 s of a detected peak; coverage = share of window seconds within +/-45 s of a peak;
  lift = explained / coverage (chance level is lift 1); regularity = IQR/median of peak intervals.
  clear : n_peaks >= 3.3*hours AND explained >= 0.40 AND lift >= 1.8 AND regularity <= 0.6
  weak  : n_peaks >= 0.83*hours AND explained >= 0.15 (and not clear)
  none  : otherwise
Direction labels (item 4) use sign(exit id - paired entry id) = stationID-ORDER HYPOTHESIS, only for paired exits.
Direction test stations: 3 busiest + 5 stations whose 10-16h exit count is closest to the median over stations."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import ctypes, json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from peak_visibility import analyse
try:
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
except Exception:
    pass
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/hangzhou/stageA"
LINES = ["A", "B", "C"]   # category order of lineID, same as stageA_pairing
ex = pd.read_pickle(ROOT / "outputs/hangzhou/cache/exits_2019-01-08.pkl")
ex["lineID"] = ex.line.map(dict(enumerate(LINES)))


rows, W1, W2 = [], (10 * 3600, 16 * 3600), (7 * 3600, 9 * 3600)
groups = {k: g.t.to_numpy() for k, g in ex.groupby(["lineID", "stationID"])}
dir_sign = {k: g.dir_sign.to_numpy() for k, g in ex.groupby(["lineID", "stationID"])}
for k, t in groups.items():
    r = dict(lineID=k[0], stationID=k[1], exits_day=len(t), labelled_dir_share=float((dir_sign[k] != 0).mean()), paired_share=float((dir_sign[k] != 0).mean()))
    r.update(analyse(t, *W1)); rows.append(r)
df = pd.DataFrame(rows).sort_values(["lineID", "stationID"])
top10 = df.sort_values("exits_window", ascending=False).head(10)
rows2 = []
for _, r in top10.iterrows():
    a = analyse(groups[(r.lineID, r.stationID)], *W2); a.update(lineID=r.lineID, stationID=r.stationID, exits_day=r.exits_day); rows2.append(a)
df2 = pd.DataFrame(rows2)
df.round(4).to_csv(OUT / "station_peak_visibility_10-16.csv", index=False); df2.round(4).to_csv(OUT / "station_peak_visibility_07-09_top10.csv", index=False)
cls_counts = df.groupby(["lineID", "cls"]).size().unstack(fill_value=0)
cls_counts.to_csv(OUT / "class_counts_per_line.csv")
none_list = df[df.cls == "none"][["lineID", "stationID", "exits_day"]].sort_values("exits_day", ascending=False)
none_list.to_csv(OUT / "none_class_stations.csv", index=False)
# ---- item 4: direction split on 8 stations
srt = df.sort_values("exits_window", ascending=False)
busy3 = srt.head(3); med = srt.exits_window.median()
mid5 = df.iloc[(df.exits_window - med).abs().argsort()[:5]]
drows = []
for grp, sel in (("busiest3", busy3), ("mid5", mid5)):
    for _, r in sel.iterrows():
        k = (r.lineID, r.stationID); t, d = groups[k], dir_sign[k]
        for label, mask in (("all_exits", np.ones(len(t), bool)), ("paired_both_dirs", d != 0), ("dir_plus(id increasing)", d > 0), ("dir_minus(id decreasing)", d < 0)):
            a = analyse(t[mask], *W1); a.update(group=grp, lineID=k[0], stationID=k[1], subset=label); drows.append(a)
dd = pd.DataFrame(drows); dd.round(4).to_csv(OUT / "direction_split_peak_visibility.csv", index=False)
summ = dict(n_stations=len(df), class_counts=df.cls.value_counts().to_dict(), per_line=cls_counts.to_dict("index"),
            top10_07_09_classes=df2.cls.value_counts().to_dict(), labelled_dir_share_overall=float((ex.dir_sign != 0).mean()),
            labelled_dir_share_station_quantiles=df.labelled_dir_share.quantile([.05, .25, .5, .75, .95]).round(3).to_dict(),
            median_peak_interval_s_clear=float(df[df.cls == "clear"].median_interval_s.median()) if (df.cls == "clear").any() else None,
            exits_share_in_none=float(df[df.cls == "none"].exits_day.sum() / df.exits_day.sum()),
            exits_share_in_clear=float(df[df.cls == "clear"].exits_day.sum() / df.exits_day.sum()))
(OUT / "peaks_summary.json").write_text(json.dumps(summ, indent=1, default=str), encoding="utf-8")
print(json.dumps(summ, indent=1, default=str)); print(none_list.head(20).to_string()); print(df2.round(3).to_string()); print(dd.round(3)[["group", "lineID", "stationID", "subset", "exits_window", "n_peaks", "explained", "lift", "regularity", "cls"]].to_string())
