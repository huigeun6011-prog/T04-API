"""Real-graph travel-time check on 2019-01-08 ONLY (Metro_roadMap.csv adjacency, BFS hop distance).
Run: .venv/Scripts/python.exe -I -X utf8 scripts/hangzhou/graph_model_check.py   (single process, threads=1, BELOW_NORMAL, no network)
Model: minutes = a + b * hops(entry stationID, exit stationID) [+ W for cross-line label pairs]
  a, b : linear fit of the per-hop lower quartile (q25, hops with n>=30) of SAME-line-label trips only (hops >= 1)
  W    : one constant per line-label pair = median residual of that pair's trips (0 for same-line unless noted)
  within-5 = share of trips with |minutes - (a + b*hops) - W| <= 5
Outputs: outputs/hangzhou/graph/graph_model_check.csv, report.md, outputs/hangzhou/station_map.csv.
User ids are never printed. Nothing here is tuned on a validation day; 2019-01-15 is not opened."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import ctypes
from collections import deque
from pathlib import Path
import numpy as np, pandas as pd
try:
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
except Exception:
    pass
ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "data/external/hangzhou"
OUT = ROOT / "outputs/hangzhou/graph"; OUT.mkdir(parents=True, exist_ok=True)

# ---- graph and station map
adj = pd.read_csv(EXT / "Metro_roadMap.csv", index_col=0).to_numpy()
assert adj.shape == (81, 81) and (adj == adj.T).all()
nbr = {i: list(np.where(adj[i] > 0)[0]) for i in range(81)}
n_edges = int(np.triu(adj, 1).sum())
dist = np.full((81, 81), -1, int)
for s in range(81):
    dist[s, s] = 0; q = deque([s])
    while q:
        u = q.popleft()
        for v in nbr[u]:
            if dist[s, v] < 0:
                dist[s, v] = dist[s, u] + 1; q.append(v)
poi = pd.read_csv(EXT / "station_poi_data.csv", encoding="utf-8-sig", usecols=["stationID", "线路", "站点"])
d = pd.read_csv(EXT / "record_2019-01-08.csv", usecols=["time", "lineID", "stationID", "status", "userID", "payType"], parse_dates=["time"])
d["t"] = (d.time - pd.Timestamp("2019-01-08")).dt.total_seconds().astype("int64")
label = d.groupby("stationID").lineID.agg(lambda x: x.mode()[0])
rows = []
for sid in range(81):
    pr = poi[poi.stationID == sid]
    rows.append(dict(stationID=sid, line_label=label.get(sid, ""), real_line=";".join(str(x) for x in sorted(pr["线路"].unique())), name_zh=pr["站点"].iloc[0],
                     shared_interchange=bool(len(pr) > 1 or (label.get(sid) == "B" and pr["线路"].iloc[0] == 4)),
                     neighbours=";".join(str(x) for x in nbr[sid])))
sm = pd.DataFrame(rows)
sm["note"] = np.where(sm.stationID.isin([10, 51]), "Fengqi Rd is two ids (line 1 / line 2), same neighbours 9,11,50,52, no direct edge", "")
sm.to_csv(ROOT / "outputs/hangzhou/station_map.csv", index=False, encoding="utf-8")
# ---- trips (exit whose immediately preceding record of the same user is an entry, <=180 min)
d = d.sort_values(["userID", "t", "status"], kind="stable").reset_index(drop=True)
same = d.userID.eq(d.userID.shift(1))
for c in ("t", "lineID", "stationID", "status"):
    d["p_" + c] = d[c].shift(1).where(same)
tr = d[(d.status == 0) & (d.p_status == 1) & ((d.t - d.p_t) <= 180 * 60)]
tr = pd.DataFrame(dict(el=tr.p_lineID.to_numpy(), xl=tr.lineID.to_numpy(), e=tr.p_stationID.astype(int).to_numpy(), x=tr.stationID.to_numpy(), m=((tr.t - tr.p_t) / 60).to_numpy()))
tr["hops"] = dist[tr.e.to_numpy(), tr.x.to_numpy()]
# ---- fit a, b on same-line trips
sl = tr[(tr.el == tr.xl) & (tr.hops >= 1)]
g = sl.groupby("hops").m.agg(q25=lambda x: x.quantile(.25), n="size"); g = g[g.n >= 30]
b, a = np.polyfit(g.index.to_numpy(), g.q25.to_numpy(), 1)
tr["pred"] = a + b * tr.hops
tr["res"] = tr.m - tr.pred
out = [dict(model="graph_hops", group="fit", n=len(sl), a=round(a, 3), b=round(b, 3), hops_used=f"{g.index.min()}-{g.index.max()}")]


def add(name, mask, w=None):
    s = tr[mask]; W = float(s.res.median()) if w is None else w; r = s.res - W
    out.append(dict(model="graph_hops", group=name, n=len(s), W=round(W, 2), within5=round(float((r.abs() <= 5).mean()), 4), median_abs=round(float(r.abs().median()), 3),
                    mean_abs=round(float(r.abs().mean()), 3)))


add("same_line_all (W=0)", (tr.el == tr.xl) & (tr.hops >= 1), 0.0)
add("same_line_all (W=median)", (tr.el == tr.xl) & (tr.hops >= 1))
for L in "ABC":
    add(f"same_line_{L} (W=median)", (tr.el == L) & (tr.xl == L) & (tr.hops >= 1))
for X, Y in (("B", "C"), ("A", "C"), ("A", "B")):
    add(f"cross_{X}{Y} (both directions pooled, W=median)", ((tr.el == X) & (tr.xl == Y)) | ((tr.el == Y) & (tr.xl == X)))
# unexplained residual by B / C side groups for B->C and C->B trips
bc = tr[((tr.el == "B") & (tr.xl == "C")) | ((tr.el == "C") & (tr.xl == "B"))].copy()
bc["bid"] = np.where(bc.el == "B", bc.e, bc.x); bc["cid"] = np.where(bc.el == "C", bc.e, bc.x)
Wbc = float(bc.res.median())
bc["r"] = bc.res - Wbc
bc["bg"] = pd.cut(bc.bid, [-1, 10, 20, 27, 33], labels=["B0-10", "B11-20", "B21-27", "B28-33(branch)"])
bc["cg"] = pd.cut(bc.cid, [33, 45, 51, 66], labels=["C34-45", "C46-51", "C52-66"])
for (bg, cg), s in bc.groupby(["bg", "cg"], observed=True):
    out.append(dict(model="graph_hops", group=f"BC residual B-group {bg} x C-group {cg}", n=len(s), median_residual_min=round(float(s.r.median()), 2), within5=round(float((s.r.abs() <= 5).mean()), 4)))
# hub model for comparison on the group B11-B20 x C34-C45 (needs stage-1 caches; skipped when absent)
try:
    import json
    models = json.load(open(ROOT / "outputs/hangzhou/cache/same_line_models.json"))["models"]
    stp = pd.read_csv(ROOT / "outputs/hangzhou/stageB0/station_positions.csv"); posC = dict(zip(stp[stp.line == "C"].stationID, stp[stp.line == "C"].pos))

    def cf(L, dd):
        m = models[L]; dv, mono = np.array(m["d"]), np.array(m["mono"]); sl_ = (mono[-1] - mono[-4]) / (dv[-1] - dv[-4])
        o = np.where(dd <= dv[-1], np.interp(dd, dv, mono), mono[-1] + sl_ * (dd - dv[-1])); return np.maximum(0.0, np.where(dd == 0, m["a"], o) - m["a"])
    hub = bc.m - cf("B", np.abs(bc.bid - 10)) - cf("C", np.abs(bc.cid.map(posC).to_numpy() - posC[51])); hub = hub - hub.median()
    sel = (bc.bid.between(11, 20)) & (bc.cid.between(34, 45))
    out.append(dict(model="direct_hub_B10-C51 (plain ID order, stage-1 style)", group="B11-20 x C34-45 median residual", n=int(sel.sum()), median_residual_min=round(float(hub[sel].median()), 2), within5=round(float((hub.abs() <= 5).mean()), 4)))
except FileNotFoundError:
    pass
res = pd.DataFrame(out); res.to_csv(OUT / "graph_model_check.csv", index=False, encoding="utf-8")
claimed = {"same_line_all (W=0)": 0.854, "cross_BC (both directions pooled, W=median)": 0.782, "cross_AC (both directions pooled, W=median)": 0.795, "cross_AB (both directions pooled, W=median)": 0.852}
lines = ["# Graph-model check (2019-01-08 only)", f"graph: 81 nodes, {n_edges} undirected edges; fit a={a:.2f} min, b={b:.2f} min/hop (hops {g.index.min()}-{g.index.max()}, same-line trips n={len(sl):,})", "",
         "| group | n | within +-5 min | claimed in brief | W (min) |", "|---|---|---|---|---|"]
for k, v in claimed.items():
    r = res[res.group == k]
    r = r.iloc[0] if len(r) else None
    lines.append(f"| {k} | {int(r.n):,} | {r.within5:.3f} | {v:.3f} | {r.get('W', float('nan'))} |" if r is not None else f"| {k} | missing |")
lines += ["", "Same-line W=0 means residual vs a+b*hops without a constant; the W=median row is shown in the csv.", "Residual by B-group x C-group for B<->C trips and the stage-1 hub comparison: see graph_model_check.csv rows 'BC residual ...' and 'direct_hub...'."]
(OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
print("a,b", round(a, 3), round(b, 3), "edges", n_edges)
print(res.to_string())
