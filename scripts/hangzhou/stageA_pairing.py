"""Stage A items 1,2 (+direction labels for item 4). ONLY record_2019-01-08.csv. Feasibility inspection, no train reconstruction.
Run: .venv/Scripts/python.exe -I scripts/hangzhou/stageA_pairing.py   (single process, threads=1, BELOW_NORMAL)
Hypothesis flag: direction = sign(exit stationID - entry stationID) relies on the stationID-order hypothesis (brief 4-2)."""
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
OUT, CACHE = ROOT / "outputs/hangzhou/stageA", ROOT / "outputs/hangzhou/cache"
OUT.mkdir(parents=True, exist_ok=True); CACHE.mkdir(parents=True, exist_ok=True)

d = pd.read_csv(SRC, usecols=["time", "lineID", "stationID", "status", "userID", "payType"], parse_dates=["time"])
d["t"] = ((d.time - pd.Timestamp("2019-01-08")).dt.total_seconds()).astype("int64")
d["line"] = d.lineID.astype("category").cat.codes.astype("int8"); lines = list(d.lineID.astype("category").cat.categories)
d = d.sort_values(["userID", "t", "status"], kind="stable").reset_index(drop=True)   # tie: exit(0) before entry(1)
same_u = d.userID.eq(d.userID.shift(1))
for c in ("t", "line", "stationID", "status"):
    d["p_" + c] = d[c].shift(1).where(same_u)
    d["n_" + c] = d[c].shift(-1).where(d.userID.eq(d.userID.shift(-1)))
res = {"rows": len(d), "lines": lines, "users": int(d.userID.nunique())}
pt = {}
# ---- item 1: exits paired with the same user's immediately preceding record being an entry on the same line (<=180 min)
ex = d[d.status == 0].copy()
gap = (ex.t - ex.p_t) / 60
cat = np.select([ex.p_t.isna(), ex.p_status == 0, ex.p_line != ex.line, gap > 180], ["no_prev", "prev_is_exit", "prev_entry_other_line", "gap_gt180"], "paired")
ex["cat"] = cat; ex["gap_min"] = gap; ex["pair"] = ex.cat == "paired"
pt["exit_status_by_payType"] = ex.groupby("payType").cat.value_counts(normalize=True).unstack(fill_value=0).round(4).to_dict("index")
pt["exit_paired_share_by_payType"] = ex.groupby("payType").pair.mean().round(4).to_dict()
pt["exit_paired_share_by_line"] = ex.groupby("line").pair.mean().round(4).rename(index=dict(enumerate(lines))).to_dict()
res["exit_paired_share_all"] = round(float(ex.pair.mean()), 4)
pq = ex[ex.pair].gap_min
res["pair_minutes_quantiles"] = {str(q): round(float(pq.quantile(q)), 1) for q in (.01, .05, .25, .5, .75, .95, .99)}
res["pair_minutes_quantiles_by_payType"] = {int(k): v.quantile([.05, .5, .95]).round(1).tolist() for k, v in ex[ex.pair].groupby("payType").gap_min}
# trips whose previous record is an entry (<=180 min), any line: entry-line -> exit-line (untagged in-system transfers show up as different lines)
tp = ex[(ex.p_status == 1) & (gap <= 180)].copy()
tp["entry_line"] = tp.p_line.map(dict(enumerate(lines))); tp["exit_line"] = tp.line.map(dict(enumerate(lines)))
lt = tp.groupby(["entry_line", "exit_line"]).agg(trips=("t", "size"), median_min=("gap_min", "median"), p10_min=("gap_min", lambda x: x.quantile(.1))).reset_index()
lt["share_of_exits"] = (lt.trips / len(ex)).round(4); lt.to_csv(OUT / "entry_line_to_exit_line_trips.csv", index=False)
res["cross_line_trips_share_of_exits"] = round(float((tp.p_line != tp.line).sum() / len(ex)), 4)
# entries: next record of same user must be an exit on the same line within 180 min
en = d[d.status == 1].copy()
g2 = (en.n_t - en.t) / 60
en["pair"] = (en.n_status == 0) & (en.n_line == en.line) & (g2 <= 180)
res["entry_paired_share_all"] = round(float(en.pair.mean()), 4)
res["entry_paired_share_by_payType"] = en.groupby("payType").pair.mean().round(4).to_dict()
res["payType_share_of_exits"] = ex.payType.value_counts(normalize=True).round(4).to_dict()
# ---- item 2: transfer-like: entry within 15 min after an exit of the same user
en["gap_prev_exit_min"] = np.where(en.p_status == 0, (en.t - en.p_t) / 60, np.nan)
tr = en[en.gap_prev_exit_min <= 15].copy()
tr["kind"] = np.select([tr.p_line != tr.line, tr.p_stationID != tr.stationID], ["different_line", "same_line_other_station"], "same_station")
res["entries"] = len(en); res["transfer_like_entries"] = len(tr); res["transfer_like_share_of_entries"] = round(len(tr) / len(en), 4)
res["transfer_by_kind_share_of_entries"] = (tr.kind.value_counts() / len(en)).round(4).to_dict()
tr["from"] = tr.p_line.map(dict(enumerate(lines))); tr["to"] = tr.line.map(dict(enumerate(lines)))
pairs = tr[tr.kind == "different_line"].groupby(["from", "to"]).size().rename("count").reset_index()
pairs["share_of_entries"] = (pairs["count"] / len(en)).round(4); pairs.to_csv(OUT / "transfer_line_pairs.csv", index=False)
gq = tr.groupby("kind").gap_prev_exit_min.quantile([.1, .5, .9]).unstack().round(2); gq.to_csv(OUT / "transfer_gap_minutes.csv")
# gap histogram over a wider range (does the short-gap mass look like transfers? compare 0-15 min vs 15-60)
wide = en[en.gap_prev_exit_min <= 60]
h = pd.cut(wide.gap_prev_exit_min, [0, 2, 5, 10, 15, 30, 60], include_lowest=True)
res["entry_after_exit_gap_hist_all_kinds"] = wide.groupby([h, np.where(wide.p_line != wide.line, "diff_line", "same_line")], observed=True).size().unstack(fill_value=0).to_dict("index") if False else None
hh = wide.assign(bin=h.astype(str), kind=np.where(wide.p_line != wide.line, "diff_line", "same_line")).groupby(["bin", "kind"]).size().unstack(fill_value=0)
hh.to_csv(OUT / "entry_after_exit_gap_hist.csv")
# transfer contamination of single-line pairing: share of paired exits whose entry was itself preceded (<=15min) by an exit on another line
pe = ex[ex.pair].copy()
pe["entry_prev_exit_gap"] = np.nan
# entry row is the previous record of the exit; find via index offset (sorted by user,t)
idx = pe.index.to_numpy() - 1
ent_gap = en.reindex(idx).gap_prev_exit_min.to_numpy(); ent_pl = en.reindex(idx).p_line.to_numpy(); ent_l = en.reindex(idx).line.to_numpy()
res["paired_exits_whose_entry_follows_other_line_exit_le15min"] = round(float(np.mean((ent_gap <= 15) & (ent_pl != ent_l))), 4)
# ---- direction labels (HYPOTHESIS: id order along line)
pe["entry_station"] = d.stationID.reindex(idx).to_numpy()
pe["dir_sign"] = np.sign(pe.stationID.to_numpy() - pe.entry_station.to_numpy()).astype(int)
ex = ex.join(pe[["entry_station", "dir_sign"]]); ex["dir_sign"] = ex.dir_sign.fillna(0).astype(int)
ex[["t", "line", "stationID", "payType", "pair", "dir_sign", "entry_station"]].to_pickle(CACHE / "exits_2019-01-08.pkl")
res["notes"] = ["direction = sign(exit id - entry id), relies on stationID-order hypothesis", "pairing: previous record of same user must be an entry on the same line, <=180 min; ties sorted exit-before-entry"]
(OUT / "pairing_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
pd.DataFrame(pt["exit_status_by_payType"]).T.to_csv(OUT / "exit_pairing_status_by_payType.csv")
print(json.dumps({k: v for k, v in res.items() if k != "entry_after_exit_gap_hist_all_kinds"}, ensure_ascii=False, default=str)[:3500]); print(pt["exit_paired_share_by_line"])
