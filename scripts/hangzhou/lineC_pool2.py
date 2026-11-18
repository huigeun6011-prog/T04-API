"""lineC_pool2: weekday pooled timetable with one-sided delay model, regularity imputation, operating-hours/abs-floor and per-station lags.
Rules frozen in outputs/hangzhou/lineC_pool2/criteria.md (written after the step-1 diagnosis, before this script ran)."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_pool as P
import lineC_stack as ST
import lineC_direct_check as DC
from lineC_route_gate import build_topology, corridor_order, read_tags
import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

OUT = P.OUT.parent / "lineC_pool2"
DAY, WALK = ST.DAY, ST.WALK
HOURS = (5 * 3600, int(23.5 * 3600))
S_ABS, QPLAN, PAIR_WIN, PAIR_MIN_SHARE = 1.0, 0.15, 90, 0.5
H_FACTOR, G_MAX, FLOW_MIN, EV_LO, EV_HI = 1.8, 4000, 0.5, 0.7, 1.3
BANDS = {"05-07": (5, 7), "07-09": (7, 9), "09-17": (9, 17), "17-19": (17, 19), "19-23:30": (19, 23.5)}
rng = np.random.default_rng(20190108)
DAYREFS = {}
CUR = {"dir": None}


def find_refs2(S):
    base = uniform_filter1d(S, ST.WIN, mode="constant") / ST.NORM
    h = np.maximum(ST.STACK_RATIO * base, S_ABS)
    h[:HOURS[0]] = np.inf
    h[HOURS[1] + 1:] = np.inf
    idx, _ = find_peaks(S, distance=ST.STACK_DIST, height=h)
    return idx, S[idx] / np.maximum(base[idx], 1e-12)


def partial_peaks(D, ks, offs):
    Sx = ST.stack([D["Z"][k] for k in ks], [offs[k] + WALK for k in ks])
    return find_refs2(Sx)[0]


def flow_series(D, pooled_dir, offs, ndays):
    """exits per minute per day in the train frame, per second index (smoothed over 5 min)."""
    F = np.zeros(DAY)
    for k, s in enumerate(D["stations"]):
        t = pooled_dir.loc[pooled_dir.exit_station == s, "exit_seconds"].to_numpy()
        h = np.bincount(t, minlength=DAY).astype(float)
        sh = int(round(offs[k] + WALK))
        if sh < DAY:
            F[:DAY - sh] += h[sh:]
    return uniform_filter1d(F, 300, mode="constant") * 60 / ndays


def local_headway(r, i):
    gs = np.diff(r)
    nb = [gs[j] for j in list(range(i - 3, i)) + list(range(i + 1, i + 4)) if 0 <= j < len(gs) and gs[j] <= 600]
    return float(np.median(nb)) if nb else 290.0


def impute(refs, D, offs, F):
    """returns sorted ref array with flags (imputed, evidence)."""
    daytime = np.median(F[10 * 3600:16 * 3600])
    first8, last8 = D["has"][:8], D["has"][-8:]
    pk_first, pk_last = partial_peaks(D, first8, offs), partial_peaks(D, last8, offs)
    new, ev = [], []
    for i in range(len(refs) - 1):
        g = refs[i + 1] - refs[i]
        h = local_headway(refs, i)
        m = int(round(g / h)) - 1
        if not (g >= H_FACTOR * h and g <= G_MAX and m >= 1):
            continue
        if refs[i] < HOURS[0] or refs[i + 1] > HOURS[1]:
            continue
        if F[int(refs[i]):int(refs[i + 1])].mean() < FLOW_MIN * daytime:
            continue
        lo, hi = refs[i] + 30, refs[i + 1] - 30
        cands = [(name, pk[(pk >= lo) & (pk <= hi)]) for name, pk in (("partial_stack_first8", pk_first), ("partial_stack_last8", pk_last))]
        pick = next(((n, p) for n, p in cands if EV_LO * m <= len(p) <= EV_HI * m), None)
        if pick:
            new += pick[1].astype(float).tolist(); ev += [pick[0]] * len(pick[1])
        else:
            pos = refs[i] + (np.arange(1, m + 1)) * g / (m + 1)
            new += pos.tolist(); ev += ["regularity"] * m
    allr = np.r_[refs.astype(float), new]
    flag = np.r_[np.zeros(len(refs), bool), np.ones(len(new), bool)]
    evid = np.array([""] * len(refs) + ev, dtype=object)
    o = np.argsort(allr, kind="stable")
    return allr[o], flag[o], evid[o]


def day_refs_cache(date, df, active):
    out = {}
    for stations in (active, active[::-1]):
        D = ST.build_direction(df, stations)
        refs, _, _, _ = ST.pipeline(D["Z"], D["cum"], D["has"])
        out[D["direction"]] = np.sort(refs.astype(float))
    return out


def plan_times(r, days):
    """one-sided plan: q15 of the paired per-day references; fails if fewer than half the days pair."""
    need = int(np.ceil(PAIR_MIN_SHARE * len(days)))
    plan, npair = r.copy(), np.zeros(len(r), int)
    vals = []
    for d in days:
        dr = DAYREFS[d][CUR["dir"]]
        j = np.clip(np.searchsorted(dr, r), 1, len(dr) - 1)
        near = np.where(np.abs(dr[j - 1] - r) <= np.abs(dr[j] - r), dr[j - 1], dr[j])
        vals.append(np.where(np.abs(near - r) <= PAIR_WIN, near, np.nan))
    V = np.column_stack(vals)
    npair = np.isfinite(V).sum(1)
    ok = npair >= need
    q = np.array([np.nanquantile(V[i], QPLAN) if ok[i] else r[i] for i in range(len(r))])
    return q, npair, ~ok


def build_pool2(days, DF, active, one_sided):
    anchors = pd.concat([DF[d] for d in days], ignore_index=True)
    nd = len(days)
    ST.BASE_FLOOR = 1e-3 * nd
    dirs = {}
    for stations in (active, active[::-1]):
        D = ST.build_direction(anchors, stations)
        dirs[D["direction"]] = D
    ST.BASE_FLOOR = 1e-3
    tabs, info, pooled_obs = {}, {}, []
    for name, D in dirs.items():
        n = len(D["stations"])
        refs, strength, adj, S = ST.pipeline(D["Z"], D["cum"], D["has"])
        offs = D["cum"] + adj
        CUR["dir"] = name
        F = flow_series(D, anchors[anchors.direction == name], offs, nd)
        r_all, imp, evid = impute(np.sort(refs.astype(float)), D, offs, F)
        if one_sided:
            plan, npair, fail = plan_times(r_all, days)
        else:
            plan, npair, fail = r_all.copy(), np.zeros(len(r_all), int), np.zeros(len(r_all), bool)
        o = np.argsort(plan, kind="stable")
        plan, imp, evid, npair, fail, r_all = plan[o], imp[o], evid[o], npair[o], fail[o], r_all[o]
        arr = plan[:, None] + offs[None, :]
        keep = (arr.min(1) >= 0) & (arr.max(1) < DAY)
        obs = ST.observed_matrix(arr[keep], D["pk"], range(n))
        pooled_obs.append(obs)
        has_ex = np.array([D["n_exits"][s] > 0 for s in D["stations"]])
        tail = np.array([(int(np.argmax(r[::-1])) if r.any() else len(r)) >= P.TAIL_N for r in (row[has_ex] for row in obs)])
        tabs[name] = dict(stations=list(D["stations"]), arr=arr[keep], refs=plan[keep])
        info[name] = dict(obs=obs, tail=tail, imputed=imp[keep], evidence=evid[keep], npair=npair[keep], fail=fail[keep], centered=r_all[keep])
    return anchors, dirs, tabs, info, ST.frag_stats(np.vstack(pooled_obs))


def gap_metrics(tabs):
    out = {}
    for name, t in tabs.items():
        r = np.sort(t["arr"][:, 0])
        inh = r[(r >= HOURS[0]) & (r <= HOURS[1])]
        svc = r[(r >= 7 * 3600) & (r <= 22 * 3600)]
        g = np.diff(svc)
        out[name] = dict(trains=len(r), outside_05_2330=int(len(r) - len(inh)), max_gap_s_05_2330=float(np.diff(inh).max()),
                         gaps_gt600_07_22=int((g > 600).sum()), max_gap_s_07_22=float(g.max()),
                         mean_headway_s={b: float(np.diff(r[(r >= lo * 3600) & (r < hi * 3600)]).mean()) for b, (lo, hi) in BANDS.items()})
    return out


def pax_hour_assignable(tabs, ps, active, Lo, Li):
    w, ok, dm = P.evaluate(tabs, ps, active, Lo, Li)
    h = (ps.X // 3600).astype(int)
    return {int(k): float(ok[h == k].mean()) for k in range(5, 24) if (h == k).sum() > 1000}, (w, ok, dm)


def variant(days, DF, active, one_sided, tag):
    anchors, dirs, tabs, info, fr = build_pool2(days, DF, active, one_sided)
    dayidx = np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(days)])
    ps = P.PaxSet(anchors, active, dayidx)
    Lo, Li, lt = P.fit_lags(tabs, ps, active)
    lt.insert(0, "group", tag)
    r = dict(trains=fr["trains"], both_ends=fr["both_ends_within_2"], small=fr["small_1_2_observed"], median_obs=fr["median_obs"],
             gaps=gap_metrics(tabs), imputed={k: int(v["imputed"].sum()) for k, v in info.items()},
             impute_evidence={k: pd.Series(v["evidence"][v["imputed"]]).value_counts().to_dict() for k, v in info.items()},
             pair_fail_share={k: float(v["fail"].mean()) for k, v in info.items()},
             median_pairs_per_train={k: float(np.median(v["npair"])) for k, v in info.items()},
             lag30_0=P.eval_group(tabs, ps, active, *P.const_lags(tabs), days=days), fitted=P.eval_group(tabs, ps, active, Lo, Li, days=days))
    return anchors, dirs, tabs, info, ps, Lo, Li, lt, r


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gate, trips, _ = read_tags()
    tracks, membership, _, _, _ = build_topology(gate)
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate.get(s) == "C"]
    first, last = active[0], active[-1]
    days = P.WEEKDAYS
    DF = {d: P.load_day(d, first, last) for d in days}
    res = {"days": days}
    # previous pool rebuilt (unpatched thresholds) for same-code comparison
    anchors0 = pd.concat([DF[d] for d in days], ignore_index=True)
    dayidx = np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(days)])
    _, tabs0, info0, fr0 = P.fit_tables(anchors0, active, refine=True)
    ps0 = P.PaxSet(anchors0, active, dayidx)
    Lo0, Li0, _ = P.fit_lags(tabs0, ps0, active)
    h0, _ = pax_hour_assignable(tabs0, ps0, active, Lo0, Li0)
    res["pool_prev_rebuilt"] = dict(trains=fr0["trains"], both_ends=fr0["both_ends_within_2"], small=fr0["small_1_2_observed"], gaps=gap_metrics(tabs0),
                                    fitted=P.eval_group(tabs0, ps0, active, Lo0, Li0, days=days), assignable_by_hour=h0)
    # single day 1/08 old stack
    _, tabs08, _, fr08 = P.fit_tables(DF["2019-01-08"], active, refine=False)
    res["single_0108"] = dict(trains=fr08["trains"], both_ends=fr08["both_ends_within_2"], small=fr08["small_1_2_observed"], gaps=gap_metrics(tabs08))
    del anchors0, ps0
    # patch thresholds, per-day references
    ST.find_refs = find_refs2
    for d in days:
        DAYREFS[d] = day_refs_cache(d, DF[d], active)
    out_variants = {}
    keep = {}
    for tag, one in (("pool2_centered", False), ("pool2", True)):
        anchors, dirs, tabs, info, ps, Lo, Li, lt, r = variant(days, DF, active, one, tag)
        out_variants[tag] = r
        keep[tag] = (anchors, dirs, tabs, info, ps, Lo, Li, lt)
        print(tag, "done", flush=True)
    res.update(out_variants)
    anchors, dirs, tabs, info, ps, Lo, Li, lt = keep["pool2"]
    ha, _ = pax_hour_assignable(tabs, ps, active, Lo, Li)
    res["pool2"]["assignable_by_hour"] = ha
    # controls
    idx = np.sort(rng.choice(len(anchors), size=len(anchors) // 4, replace=False))
    dayidx = ps.day
    ps_s = P.PaxSet(anchors.iloc[idx].reset_index(drop=True), active, dayidx[idx])
    ctrl = {}
    for nm, fn, reps in (("pool2_real", lambda t: t, 1), ("direction_swap", DC.swapped, 1), ("local_shuffle5", lambda t: DC.local_shuffle(t, rng), 3),
                         ("random_timetable", lambda t: DC.random_tt(t, rng), 3)):
        ms = []
        for _ in range(reps):
            tt = fn(tabs)
            lo_, li_, _ = P.fit_lags(tt, ps_s, active)
            ms.append(P.eval_group(tt, ps_s, active, lo_, li_)["all"])
        ctrl[nm] = {k: float(np.mean([m[k] for m in ms])) for k in ms[0]}
    res["controls_refit_lags_25pct"] = ctrl
    # holdout day
    hd = "2019-01-16"
    rest = [d for d in days if d != hd]
    anc_r, _, tabs_r, info_r, fr_r = build_pool2(rest, DF, active, True)
    ps_r = P.PaxSet(anc_r, active, np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(rest)]))
    Lo_r, Li_r, _ = P.fit_lags(tabs_r, ps_r, active)
    ps_h = P.PaxSet(DF[hd], active)
    res["holdout_day"] = dict(day=hd, trains=fr_r["trains"], gaps=gap_metrics(tabs_r), without_day_fitted=P.eval_group(tabs_r, ps_h, active, Lo_r, Li_r)["all"],
                              with_day_fitted=res["pool2"]["fitted"][hd], prev_pool_with_day=res["pool_prev_rebuilt"]["fitted"][hd])
    # events
    ev = []
    for name, t in tabs.items():
        inf = info[name]
        for i in range(len(t["arr"])):
            tid = f"C-weekday2-{name}-P{i + 1:04d}"
            for k, s in enumerate(t["stations"]):
                sec = t["arr"][i, k]
                ev.append(("weekday", tid, name, int(s), f"{int(sec) // 3600:02d}:{int(sec) % 3600 // 60:02d}:{int(sec) % 60:02d}", bool(inf["obs"][i, k]),
                           bool(inf["imputed"][i]), inf["evidence"][i], int(inf["npair"][i]), bool(inf["fail"][i]), round(float(Lo[name][k]), 1),
                           round(float(Li[name][k]), 1), bool(inf["tail"][i])))
    pd.DataFrame(ev, columns=["group", "train_id", "direction", "stationID", "arrival_time_of_day", "observed_peak_within_45s", "imputed", "impute_evidence",
                              "plan_paired_days", "plan_pairing_failed", "lag_out_s", "lag_in_s", "tail_unsupported_flag"]).to_csv(OUT / "candidate_arrival_events_pool2.csv", index=False)
    lt.to_csv(OUT / "lags_by_station_pool2.csv", index=False, float_format="%.2f")
    res["tail_unsupported_share"] = float(np.mean(np.r_[info[f"toward_{first}"]["tail"], info[f"toward_{last}"]["tail"]]))
    (OUT / "pool2_metrics.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")
    # figure data: T0 timeline (gap) per direction for prev / pool2
    fd = {}
    for lab, tt in (("prev_pool", tabs0), ("pool2", tabs)):
        fd[lab] = {n: np.sort(t["arr"][:, 0]).tolist() for n, t in tt.items()}
    fd["pool2_imputed"] = {n: np.sort(tabs[n]["arr"][info[n]["imputed"], 0]).tolist() for n in tabs}
    (OUT / "fig_data.json").write_text(json.dumps(fd), encoding="utf-8")
    print(json.dumps({k: res[k] for k in res if k not in ("days",)}, indent=1, default=float, ensure_ascii=False)[:12000])


if __name__ == "__main__":
    main()
