"""Day-level scan of Hangzhou tag files: counts only, no reconstruction."""
import json, os, sys, glob
os.environ.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
import pandas as pd
try:
    import ctypes; ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
except Exception:
    pass
D = "data/external/hangzhou"; OUT = "outputs/hangzhou"
rows, sets = [], {}
for f in sorted(glob.glob(f"{D}/record_2019-01-*.csv")):
    day = f[-14:-4]
    df = pd.read_csv(f, usecols=["time", "lineID", "stationID", "status", "userID"],
                     dtype={"lineID": "category", "stationID": "int16", "status": "int8"}, parse_dates=["time"])
    st = df.groupby("lineID", observed=True)["stationID"].nunique().to_dict()
    sets[day] = {l: sorted(g.unique().tolist()) for l, g in df.groupby("lineID", observed=True)["stationID"]}
    h = df["time"].dt.hour
    r = dict(date=day, weekday=pd.Timestamp(day).day_name(), rows=len(df), entries=int((df.status == 1).sum()),
             exits=int((df.status == 0).sum()), users=int(df.userID.nunique()),
             first=str(df.time.min()), last=str(df.time.max()),
             stations_A=st.get("A", 0), stations_B=st.get("B", 0), stations_C=st.get("C", 0),
             peak_morning=int(((h >= 7) & (h < 9)).sum()), peak_evening=int(((h >= 17) & (h < 19)).sum()))
    rows.append(r); print(day, r["weekday"], r["rows"], st, flush=True)
tab = pd.DataFrame(rows); tab.to_csv(f"{OUT}/day_scan.csv", index=False)
base = sets["2019-01-08"]; diff = {}
for d, s in sets.items():
    x = {l: {"new": sorted(set(s.get(l, [])) - set(base.get(l, []))), "missing": sorted(set(base.get(l, [])) - set(s.get(l, [])))} for l in "ABC"}
    if any(v["new"] or v["missing"] for v in x.values()): diff[d] = x
json.dump(diff, open(f"{OUT}/day_scan_station_diff_vs_0108.json", "w"), ensure_ascii=False, indent=1)
print("station-set differences vs 2019-01-08:", json.dumps(diff, ensure_ascii=False))
