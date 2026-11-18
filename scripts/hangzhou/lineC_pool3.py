"""lineC_pool3: pool2 + relaxed-stack filling of under-represented direction x band cells (E1 expected counts). Rules: outputs/hangzhou/lineC_pool3/criteria.md."""
import json, pickle
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_pool as P
import lineC_pool2 as P2
import lineC_stack as ST
from lineC_route_gate import build_topology, corridor_order, read_tags
import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

OUT = P.OUT.parent / "lineC_pool3"
CACHE = P.CACHE
DAY, WALK, HOURS = ST.DAY, ST.WALK, P2.HOURS
BANDS = [("05-07", 5, 7), ("07-09", 7, 9), ("09-17", 9, 17), ("17-19", 17, 19), ("19-23:30", 19, 23.5)]
SHORT, CAP, MAXTOT, GAPF, RATIO_LO, SPACE = 0.85, 0.40, 1.05, 1.3, 1.2, 0.5


def e1_expected():
    E = pd.read_csv(P.OUT.parent / "lineC_struct/e1_headway_by_station.csv")
    E = E[E.informative & E.pos.between(4, 27)]
    g = E.groupby(["direction", "band"]).headway_s.agg(["median", "count"])
    return {k: float(v["median"]) for k, v in g.iterrows() if v["count"] >= 3}


def relaxed_fill(r_all, imp, evid, S, dname, H):
    base = uniform_filter1d(S, ST.WIN, mode="constant") / ST.NORM
    h = np.maximum(RATIO_LO * base, P2.S_ABS)
    h[:HOURS[0]] = np.inf; h[HOURS[1] + 1:] = np.inf
    pk, _ = find_peaks(S, distance=60, height=h)
    new, log = [], []
    for bn, lo, hi in BANDS:
        Hb = H.get((dname, bn))
        inb = (r_all >= lo * 3600) & (r_all < hi * 3600)
        N = int(inb.sum())
        if Hb is None:
            log.append(dict(direction=dname, band=bn, N=N, N_exp=np.nan, added=0, note="E1 expected unavailable")); continue
        Nexp = (hi - lo) * 3600 / Hb
        add = min(int(round(Nexp)) - N, int(np.floor(CAP * N)), int(np.floor(MAXTOT * Nexp)) - N)
        if N > SHORT * Nexp or add <= 0:
            log.append(dict(direction=dname, band=bn, N=N, N_exp=Nexp, added=0, note="not short" if N > SHORT * Nexp else "cap")); continue
        r = r_all[inb]
        caps, cands = {}, []
        for i in range(len(r) - 1):
            g = r[i + 1] - r[i]
            if g >= GAPF * Hb:
                caps[i] = int(round(g / Hb)) - 1
                for p in pk[(pk > r[i] + SPACE * Hb) & (pk < r[i + 1] - SPACE * Hb)]:
                    cands.append((S[p], i, float(p)))
        cands.sort(reverse=True)
        used, acc = {}, []
        allr = list(r)
        for s_, i, p in cands:
            if len(acc) >= add:
                break
            if used.get(i, 0) >= caps.get(i, 0):
                continue
            if min(abs(np.array(allr) - p)) < SPACE * Hb:
                continue
            acc.append(p); allr.append(p); used[i] = used.get(i, 0) + 1
        new += acc
        log.append(dict(direction=dname, band=bn, N=N, N_exp=Nexp, added=len(acc), wanted=add, note=""))
    if new:
        r_all = np.r_[r_all, new]; imp = np.r_[imp, np.ones(len(new), bool)]; evid = np.r_[evid, np.array(["relaxed_stack"] * len(new), dtype=object)]
        o = np.argsort(r_all, kind="stable")
        r_all, imp, evid = r_all[o], imp[o], evid[o]
    return r_all, imp, evid, log


def build_pool3(days, DF, active, H):
    anchors = pd.concat([DF[d] for d in days], ignore_index=True)
    nd = len(days)
    ST.BASE_FLOOR = 1e-3 * nd
    dirs = {}
    for stations in (active, active[::-1]):
        D = ST.build_direction(anchors, stations)
        dirs[D["direction"]] = D
    ST.BASE_FLOOR = 1e-3
    tabs, info, pooled_obs, logs = {}, {}, [], []
    for name, D in dirs.items():
        n = len(D["stations"])
        refs, strength, adj, S = ST.pipeline(D["Z"], D["cum"], D["has"])
        offs = D["cum"] + adj
        P2.CUR["dir"] = name
        F = P2.flow_series(D, anchors[anchors.direction == name], offs, nd)
        r_all, imp, evid = P2.impute(np.sort(refs.astype(float)), D, offs, F)
        r_all, imp, evid, log = relaxed_fill(r_all, imp, evid, S, name, H)
        logs += log
        plan, npair, fail = P2.plan_times(r_all, days)
        o = np.argsort(plan, kind="stable")
        plan, imp, evid, npair, fail = plan[o], imp[o], evid[o], npair[o], fail[o]
        arr = plan[:, None] + offs[None, :]
        keep = (arr.min(1) >= 0) & (arr.max(1) < DAY)
        obs = ST.observed_matrix(arr[keep], D["pk"], range(n))
        pooled_obs.append(obs)
        has_ex = np.array([D["n_exits"][s] > 0 for s in D["stations"]])
        tail = np.array([(int(np.argmax(r[::-1])) if r.any() else len(r)) >= P.TAIL_N for r in (row[has_ex] for row in obs)])
        tabs[name] = dict(stations=list(D["stations"]), arr=arr[keep], refs=plan[keep])
        info[name] = dict(obs=obs, tail=tail, imputed=imp[keep], evidence=evid[keep], npair=npair[keep], fail=fail[keep])
    return anchors, dirs, tabs, info, ST.frag_stats(np.vstack(pooled_obs)), logs


def evaluate_all(tabs, anchors, days, active, fr):
    dayidx = np.concatenate([np.full((anchors.direction.values.shape[0] // len(days)), i) for i in range(len(days))]) if False else None
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gate, trips, _ = read_tags()
    tracks, membership, _, _, _ = build_topology(gate)
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate.get(s) == "C"]
    first, last = active[0], active[-1]
    days = P.WEEKDAYS
    DF = {d: P.load_day(d, first, last) for d in days}
    ST.find_refs = P2.find_refs2
    for d in days:
        P2.DAYREFS[d] = P2.day_refs_cache(d, DF[d], active)
    H = e1_expected()
    res = {"E1_expected_headway_s": {f"{k[0]}|{k[1]}": v for k, v in H.items()}, "days": days}
    # pool2 rebuilt
    _, _, tabs2, info2, ps2, Lo2, Li2, _, r2 = P2.variant(days, DF, active, True, "pool2")
    h2, _ = P2.pax_hour_assignable(tabs2, ps2, active, Lo2, Li2)
    r2["assignable_by_hour"] = h2
    res["pool2"] = r2
    del ps2

    def run(days_, tag, eval_days=None):
        anchors, dirs, tabs, info, fr, logs = build_pool3(days_, DF, active, H)
        dayidx = np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(days_)])
        ps = P.PaxSet(anchors, active, dayidx)
        Lo, Li, lt = P.fit_lags(tabs, ps, active)
        return anchors, tabs, info, fr, logs, ps, Lo, Li, lt

    anchors, tabs, info, fr, logs, ps, Lo, Li, lt = run(days, "pool3")
    r3 = dict(trains=fr["trains"], both_ends=fr["both_ends_within_2"], small=fr["small_1_2_observed"], median_obs=fr["median_obs"], gaps=P2.gap_metrics(tabs),
              imputed={k: int(v["imputed"].sum()) for k, v in info.items()}, relaxed_added={k: int((v["evidence"] == "relaxed_stack").sum()) for k, v in info.items()},
              fill_log=logs, pair_fail_share={k: float(v["fail"].mean()) for k, v in info.items()},
              lag30_0=P.eval_group(tabs, ps, active, *P.const_lags(tabs), days=days), fitted=P.eval_group(tabs, ps, active, Lo, Li, days=days))
    h3, _ = P2.pax_hour_assignable(tabs, ps, active, Lo, Li)
    r3["assignable_by_hour"] = h3
    res["pool3"] = r3
    # symmetry
    sym = {}
    for lab, g in (("pool2", r2["gaps"]), ("pool3", r3["gaps"])):
        sym[lab] = {b: float(g[f"toward_{first}"]["mean_headway_s"][b] / g[f"toward_{last}"]["mean_headway_s"][b]) for b in g[f"toward_{first}"]["mean_headway_s"]}
    res["headway_ratio_toward34_over_toward66"] = sym
    # holdout day
    hd = "2019-01-16"
    rest = [d for d in days if d != hd]
    anc_r, tabs_r, info_r, fr_r, logs_r, ps_r, Lo_r, Li_r, _ = run(rest, "pool3_rest")
    ps_h = P.PaxSet(DF[hd], active)
    res["holdout_day"] = dict(day=hd, trains=fr_r["trains"], relaxed_added={k: int((v["evidence"] == "relaxed_stack").sum()) for k, v in info_r.items()},
                              without_day_fitted=P.eval_group(tabs_r, ps_h, active, Lo_r, Li_r)["all"], with_day_fitted=r3["fitted"][hd], pool2_with_day=r2["fitted"][hd],
                              gaps=P2.gap_metrics(tabs_r))
    # events + cache
    ev = []
    for name, t in tabs.items():
        inf = info[name]
        for i in range(len(t["arr"])):
            tid = f"C-weekday3-{name}-P{i + 1:04d}"
            for k, s in enumerate(t["stations"]):
                sec = t["arr"][i, k]
                ev.append(("weekday", tid, name, int(s), f"{int(sec) // 3600:02d}:{int(sec) % 3600 // 60:02d}:{int(sec) % 60:02d}", bool(inf["obs"][i, k]), bool(inf["imputed"][i]),
                           inf["evidence"][i], int(inf["npair"][i]), bool(inf["fail"][i]), round(float(Lo[name][k]), 1), round(float(Li[name][k]), 1), bool(inf["tail"][i])))
    pd.DataFrame(ev, columns=["group", "train_id", "direction", "stationID", "arrival_time_of_day", "observed_peak_within_45s", "imputed", "impute_evidence",
                              "plan_paired_days", "plan_pairing_failed", "lag_out_s", "lag_in_s", "tail_unsupported_flag"]).to_csv(OUT / "candidate_arrival_events_pool3.csv", index=False)
    lt.to_csv(OUT / "lags_by_station_pool3.csv", index=False, float_format="%.2f")
    pd.DataFrame(logs).to_csv(OUT / "fill_log.csv", index=False, float_format="%.2f")
    with open(CACHE / "pool3_final.pkl", "wb") as f:
        pickle.dump(dict(tabs=tabs, Lo=Lo, Li=Li, active=active, days=days, imputed={k: v["imputed"] for k, v in info.items()}), f)
    fd = {lab: {n: np.sort(t["arr"][:, 0]).tolist() for n, t in tt.items()} for lab, tt in (("pool2", tabs2), ("pool3", tabs))}
    (OUT / "fig_data.json").write_text(json.dumps(fd), encoding="utf-8")
    (OUT / "pool3_metrics.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("headway_ratio_toward34_over_toward66", "holdout_day")}, indent=1, default=float, ensure_ascii=False))


if __name__ == "__main__":
    main()
