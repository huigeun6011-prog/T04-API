"""Stage B0 step 0/1: trips and same-line travel-time model, 2019-01-08 ONLY (no other day is opened).
Run: .venv/Scripts/python.exe -I scripts/hangzhou/stageB0_prepare.py     (single process, threads=1, BELOW_NORMAL)
ASSUMPTIONS (flagged): station position along a line = rank of stationID inside the line block (ID-order hypothesis); no branches resolved.
DECLARED BEFORE RESULTS (see also stageB0_hubs.py header):
  trip = exit whose immediately preceding record of the same user is an entry (<=180 min), any line.
  same-line leg time model: q25 of (exit-entry) minutes by d=|pos diff| (n>=30 per d, payType 0-2 + 3 all used), made monotone by cummax,
     intercept a_L = linear fit over d=1..8; c_L(d) = max(0, mono(d) - a_L) (in-vehicle-like part; the constant goes into W), beyond max d linear extrapolation.
  adjacent-station anomaly flag: q25 of adjacent pairs (n>=30) > 1.8 x or < 0.4 x the line's median adjacent q25."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import ctypes, json
from pathlib import Path
import numpy as np, pandas as pd
try:
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
except Exception:
    pass
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data/external/hangzhou/record_2019-01-08.csv"
OUT, CACHE = ROOT / "outputs/hangzhou/stageB0", ROOT / "outputs/hangzhou/cache"
d = pd.read_csv(SRC, usecols=["time", "lineID", "stationID", "status", "userID", "payType"], parse_dates=["time"])
d["t"] = (d.time - pd.Timestamp("2019-01-08")).dt.total_seconds().astype("int64")
# station table: line of each stationID, position = rank of id inside its line
st = d.groupby("stationID").lineID.agg(lambda x: x.mode()[0]).rename("line").reset_index()
assert d.groupby("stationID").lineID.nunique().max() == 1
st["pos"] = st.groupby("line").stationID.rank(method="first").astype(int) - 1
st.to_csv(OUT / "station_positions.csv", index=False)
daily = d.groupby(["stationID", "status"]).size().unstack(fill_value=0).rename(columns={0: "exits", 1: "entries"}); daily.to_pickle(CACHE / "station_taps_B0.pkl")
pos = st.set_index("stationID").pos
d = d.sort_values(["userID", "t", "status"], kind="stable").reset_index(drop=True)
same = d.userID.eq(d.userID.shift(1))
for c in ("t", "lineID", "stationID", "status"):
    d["p_" + c] = d[c].shift(1).where(same)
tr = d[(d.status == 0) & (d.p_status == 1) & ((d.t - d.p_t) <= 180 * 60)].copy()
tr = tr.assign(entry_line=tr.p_lineID, exit_line=tr.lineID, entry_st=tr.p_stationID.astype(int), exit_st=tr.stationID, minutes=(tr.t - tr.p_t) / 60,
               entry_pos=pos.reindex(tr.p_stationID.astype(int)).to_numpy(), exit_pos=pos.reindex(tr.stationID).to_numpy())
tr = tr[["userID", "payType", "entry_line", "exit_line", "entry_st", "exit_st", "entry_pos", "exit_pos", "minutes", "p_t", "t"]].reset_index(drop=True)
tr.to_pickle(CACHE / "trips_2019-01-08.pkl")
# ---- same-line model
res, models, anom = {}, {}, []
for L in "ABC":
    s = tr[(tr.entry_line == L) & (tr.exit_line == L)].copy(); s["dd"] = (s.entry_pos - s.exit_pos).abs()
    s = s[s.dd >= 1]
    g = s.groupby("dd").minutes.agg(q25=lambda x: x.quantile(.25), n="size"); g = g[g.n >= 30]
    mono = np.maximum.accumulate(g.q25.to_numpy()); dd = g.index.to_numpy()
    sel = dd <= 8; slope, a = np.polyfit(dd[sel], mono[sel], 1)
    models[L] = dict(a=float(a), slope=float(slope), dmax=int(dd.max()), d=dd.tolist(), mono=mono.tolist())
    # adjacent-pair anomalies
    lo = np.minimum(s.entry_st, s.exit_st); hi = np.maximum(s.entry_st, s.exit_st); adj = s[(s.dd == 1)].assign(lo=lo, hi=hi)
    ag = adj.groupby("lo").minutes.agg(q25=lambda x: x.quantile(.25), n="size"); ag = ag[ag.n >= 30]
    med = ag.q25.median()
    for k, r in ag.iterrows():
        if r.q25 > 1.8 * med or r.q25 < .4 * med:
            anom.append(dict(line=L, station_lo=int(k), q25_min=round(float(r.q25), 2), line_median_adjacent_q25=round(float(med), 2), n=int(r.n)))
    res[L] = dict(n_same_line_trips=int(len(s)), intercept_min=round(float(a), 2), slope_min_per_station=round(float(slope), 2), max_d=int(dd.max()),
                  median_adjacent_q25=round(float(med), 2), n_adjacent_pairs_checked=int(len(ag)))
json.dump(dict(models=models), open(CACHE / "same_line_models.json", "w"))
pd.DataFrame(anom).to_csv(OUT / "adjacent_anomalies.csv", index=False)
res["cross_line_trips"] = int((tr.entry_line != tr.exit_line).sum()); res["all_trips"] = len(tr); res["n_anomalous_adjacent"] = len(anom)
res["cross_by_pair"] = tr[tr.entry_line != tr.exit_line].groupby(["entry_line", "exit_line"]).size().to_dict().__repr__()
(OUT / "same_line_model.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(res, indent=1, ensure_ascii=False)); print(pd.DataFrame(anom).to_string() if anom else "no anomalies")
