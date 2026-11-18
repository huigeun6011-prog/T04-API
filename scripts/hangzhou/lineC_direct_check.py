"""Does the line-C timetable hold when transfers are excluded? 2019-01-08 only. Criteria are frozen in
outputs/hangzhou/lineC_direct_check/criteria.md before this ran. Reuses lineC_stack.py functions/constants unchanged."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_stack as ST
from lineC_direct import direct_directions
from lineC_route_gate import DATE, ROOT, build_topology, corridor_order, graph_distances, read_tags
import numpy as np
import pandas as pd

OUT = ROOT / "outputs/hangzhou/lineC_direct_check"
WALK, DWELL, MAXGAP, WIN_HI = 30, 30, 600, 600
BANDS = {"commute": [(7, 9), (17, 19)], "midday": [(9, 17)], "evening": [(19, 24)], "early": [(5, 7)]}


def band_of(sec):
    h = sec / 3600
    out = np.full(len(sec), "other", dtype=object)
    for b, rngs in BANDS.items():
        for lo, hi in rngs:
            out[(h >= lo) & (h < hi)] = b
    return out


# ---------------- timetable (same pipeline as lineC_stack.main, parametrised by anchors) ----------------
def build_tabs(anchors, active, interior, rng):
    dirs = {}
    for stations in (active, active[::-1]):
        D = ST.build_direction(anchors, stations)
        dirs[D["direction"]] = D
    tabs, pooled, obs_cells, obs_st = {}, [], 0, set()
    for name, D in dirs.items():
        n = len(D["stations"])
        refs, strength, adj, S = ST.pipeline(D["Z"], D["cum"], D["has"])
        keep, arr = ST.make_trains(D, D["has"], adj, refs, strength)
        obs = ST.observed_matrix(arr[keep], D["pk"], range(n))
        pooled.append(obs)
        obs_cells += int(obs.sum())
        obs_st |= {D["stations"][k] for k in np.flatnonzero(obs.any(0))}
        tabs[name] = dict(stations=list(D["stations"]), arr=arr[keep], refs=refs[keep])
    fr = ST.frag_stats(np.vstack(pooled))
    summ = dict(n_trains=int(fr["trains"]), both_ends_within_2=fr["both_ends_within_2"], small_1_2_observed=fr["small_1_2_observed"],
                median_obs=fr["median_obs"], observed_cells=obs_cells, stations_with_any_observed=len(obs_st),
                stations_with_peaks=len({D["stations"][k] for D in dirs.values() for k, p in enumerate(D["pk"]) if len(p)}),
                anchors=int(len(anchors)),
                peaks_total=int(sum(len(p) for D in dirs.values() for p in D["pk"])))
    return dirs, tabs, summ


def holdout(dirs, active, interior, eval_ok, rng):
    """same folds/controls as lineC_stack.main; recall only on hidden stations in eval_ok."""
    rows = []
    for fold in range(3):
        hid = {active[k] for i, k in enumerate(interior) if i % 3 == fold}
        for name, D in dirs.items():
            st = D["stations"]
            hidx = [k for k, s in enumerate(st) if s in hid]
            vis = [k for k in D["has"] if k not in hidx]
            refs, strength, adj, S = ST.pipeline(D["Z"], D["cum"], vis)
            full_adj = ST.interp_adj(adj, np.array(vis), len(st))
            keep, arr = ST.make_trains(D, vis, full_adj, refs, strength)
            arr = arr[keep]
            for k in hidx:
                if st[k] not in eval_ok:
                    continue
                pk, pred = D["pk"][k], arr[:, k]
                ctrl = [float(ST.support_rec(pred + rng.uniform(120, 600) * rng.choice([-1, 1]), pk)) for _ in range(200)]
                rows.append(dict(fold=fold, direction=name, stationID=int(st[k]), peaks=len(pk),
                                 recall=float(ST.support_rec(pred, pk)), ctrl=float(np.mean(ctrl))))
    H = pd.DataFrame(rows)
    w = H.peaks
    return dict(cells=len(H), peaks=int(w.sum()), recall=float(np.average(H.recall, weights=w)), ctrl_mean=float(np.average(H.ctrl, weights=w)))


# ---------------- passenger feasibility ----------------
def prep(tabs):
    P = {}
    for lab, t in tabs.items():
        col = {s: k for k, s in enumerate(t["stations"])}
        order = np.argsort(t["arr"], axis=0)
        vals = np.take_along_axis(t["arr"], order, axis=0)
        P[lab] = dict(arr=t["arr"], col=col, order=order, vals=vals)
    return P


def preceding(Pl, x, X):
    k = Pl["col"][x]
    v = Pl["vals"][:, k]
    j = np.searchsorted(v, X - WALK, side="right") - 1
    gap = np.where(j >= 0, X - WALK - v[np.clip(j, 0, None)], np.inf)
    return Pl["order"][np.clip(j, 0, None), k], gap


def evaluate(tabs, pax):
    P = prep(tabs)
    n = len(pax)
    wait, ok, dmatch = np.full(n, np.nan), np.zeros(n, bool), np.full(n, np.nan)
    d = pax.d.to_numpy()
    for (lab, x), g in pax.groupby(["d", "x"]):
        idx = g.index.to_numpy()
        tr, gap = preceding(P[lab], x, g.X.to_numpy())
        good = gap <= MAXGAP
        D0 = np.array([P[lab]["arr"][t, P[lab]["col"][e]] for t, e in zip(tr, g.e.to_numpy())]) + DWELL
        wait[idx] = np.where(good, D0 - g.E.to_numpy(), np.nan)
        ok[idx] = good
    labs = list(tabs)
    for x, g in pax.groupby("x"):
        idx = g.index.to_numpy()
        gaps = np.column_stack([preceding(P[l], x, g.X.to_numpy())[1] for l in labs])
        best = gaps.argmin(1)
        has = gaps.min(1) <= MAXGAP
        dmatch[idx] = np.where(has, (np.array(labs)[best] == d[idx]).astype(float), np.nan)
    return wait, ok, dmatch


def metrics(wait, ok, dmatch, mask):
    w, o, m = wait[mask], ok[mask], dmatch[mask]
    wv = w[o]
    q = np.quantile(wv, [.05, .25, .5, .75, .95]) if len(wv) else [np.nan] * 5
    return dict(n=int(mask.sum()), assignable=float(o.mean()), neg=float((wv < 0).mean()), window=float(((wv >= 0) & (wv <= WIN_HI)).mean()),
                over=float((wv > WIN_HI).mean()), q05=float(q[0]), q25=float(q[1]), q50=float(q[2]), q75=float(q[3]), q95=float(q[4]),
                dir_match=float(np.nanmean(m)) if np.isfinite(m).any() else np.nan)


def full_metrics(tabs, pax):
    wait, ok, dm = evaluate(tabs, pax)
    bands = pax.band.to_numpy()
    res = {"all": metrics(wait, ok, dm, np.ones(len(pax), bool))}
    for b in ("commute", "midday", "evening", "early"):
        res[b] = metrics(wait, ok, dm, bands == b)
    return res, wait[ok]


# ---------------- null timetables ----------------
def shifted(tabs, s):
    return {l: dict(t, arr=t["arr"] + s) for l, t in tabs.items()}


def swapped(tabs):
    a, b = list(tabs)
    return {a: tabs[b], b: tabs[a]}


def local_shuffle(tabs, rng, blk=5):
    out = {}
    for l, t in tabs.items():
        arr = t["arr"].copy()
        for k in range(arr.shape[1]):
            for s in range(0, len(arr), blk):
                arr[s:s + blk, k] = rng.permutation(arr[s:s + blk, k])
        out[l] = dict(t, arr=arr)
    return out


def random_tt(tabs, rng):
    out = {}
    for l, t in tabs.items():
        offs = t["arr"][0] - t["refs"][0]
        refs = np.sort(rng.uniform(t["refs"].min(), t["refs"].max(), len(t["refs"])))
        out[l] = dict(t, arr=refs[:, None] + offs[None, :], refs=refs)
    return out


def circ(tabs, rng):
    out = {}
    for l, t in tabs.items():
        sh = np.array([int(rng.integers(900, 3000)) * rng.choice([-1, 1]) for _ in range(t["arr"].shape[1])])
        out[l] = dict(t, arr=t["arr"] + sh[None, :])
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20190108)
    gate_line, trips, all_exits = read_tags()
    tracks, membership, transfers, _, _ = build_topology(gate_line)
    graph_distances({"C": tracks["C"]})
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate_line.get(s) == "C"]
    anchors = direct_directions(trips, corridor, membership)
    shared = {s for s in active if len(membership[s]) > 1}
    res = {"date": DATE}

    # ---- 0. fact: which C exit tags did the original use ----
    tc = trips[trips.exit_line.eq("C")]
    n_all, n_pair = len(all_exits), len(tc)
    res["facts"] = dict(
        c_exit_tags=n_all, paired_with_prev_entry_0_180min=n_pair, unpaired_or_gap_out=n_all - n_pair,
        paired_entry_line_A=int(tc.entry_line.eq("A").sum()), paired_entry_line_B=int(tc.entry_line.eq("B").sum()),
        paired_entry_C_same_station=int((tc.entry_line.eq("C") & tc.entry_station.eq(tc.exit_station)).sum()),
        used_anchors=len(anchors), used_share=len(anchors) / n_all, dropped_share=1 - len(anchors) / n_all,
        anchors_with_shared_endpoint=int(anchors.shared_endpoint.sum()),
        exits_at_C_in_anchors_by_direction=anchors.direction.value_counts().to_dict())

    # ---- TR set ----
    poi = pd.read_csv(ST.ROOT / "data/external/hangzhou/station_poi_data.csv", usecols=["stationID", "站点"])
    name = dict(zip(poi.stationID, poi["站点"].str.replace(r"[A-Z]?站$", "", regex=True)))
    c_nodes = set(tracks["C"])
    other_names = {name[s] for L in "AB" for s in tracks[L]}
    tr_pairs = {a for L in "AB" for a, b in transfers[("C", L)]} & c_nodes
    TR = tr_pairs | {s for s in c_nodes if len(membership[s]) > 1} | {s for s in c_nodes if name[s] in other_names}
    res["TR_stations"] = sorted(int(s) for s in TR)
    res["TR_in_active"] = sorted(int(s) for s in TR if s in active)
    strict = anchors.loc[~anchors.entry_station.isin(TR) & ~anchors.exit_station.isin(TR)].copy()
    res["facts"]["strict_anchors"] = len(strict)
    res["facts"]["strict_share_of_c_exits"] = len(strict) / n_all
    res["facts"]["anchors_with_TR_endpoint"] = int((~anchors.index.isin(strict.index)).sum())

    interior = [k for k in range(1, len(active) - 1) if active[k] not in shared and active[k] != 54]
    hid_all = {active[k] for k in interior}
    eval_ok = hid_all - TR

    # ---- timetables ----
    dA, tA, sA = build_tabs(anchors, active, interior, rng)
    dB, tB, sB = build_tabs(strict, active, interior, rng)
    # reproduce stored events
    ev = pd.read_csv(ST.OUT / "candidate_arrival_events_stack.csv", usecols=["direction", "stationID", "arrival_time"], parse_dates=["arrival_time"])
    res["reproduces_stack_csv_trains"] = int(sum(len(t["arr"]) for t in tA.values()))
    res["csv_trains"] = int(ev.groupby("direction").size().sum() // (len(active)))
    t0 = pd.Timestamp(DATE)
    dev = 0.0
    for lab, t in tA.items():
        e = ev[ev.direction == lab].assign(sec=lambda d: (d.arrival_time - t0).dt.total_seconds())
        m = e.pivot_table(index=e.groupby("stationID").cumcount(), columns="stationID", values="sec")
        dev = max(dev, float(np.abs(m[t["stations"]].to_numpy() - t["arr"]).max())) if m.shape == t["arr"].shape else float("inf")
    res["max_abs_dev_vs_csv_s"] = dev
    res["timetable_summary"] = {"a_direct_anchor": sA, "b_strict": sB}
    res["holdout"] = {"a_direct_anchor": holdout(dA, active, interior, eval_ok, rng), "b_strict": holdout(dB, active, interior, eval_ok, rng)}

    # ---- passengers ----
    pax = anchors.assign(e=anchors.entry_station, x=anchors.exit_station, X=anchors.exit_seconds, d=anchors.direction)
    pax["E"] = pax.X - pax.minutes * 60
    pax["band"] = band_of(pax.X.to_numpy())
    pax["common"] = ~(pax.e.isin(TR) | pax.x.isin(TR))
    pax = pax[["e", "x", "X", "E", "d", "band", "common"]].reset_index(drop=True)
    res["passengers"] = dict(n=len(pax), n_common=int(pax.common.sum()), by_band=pax.band.value_counts().to_dict())
    common = pax[pax.common].reset_index(drop=True)

    base, wbase = full_metrics(tA, pax)
    res["metrics_a_all_pax"] = base
    res["metrics_a_common_pax"], _ = full_metrics(tA, common)
    res["metrics_b_common_pax"], wb = full_metrics(tB, common)
    res["metrics_b_all_pax"], _ = full_metrics(tB, pax)

    # ---- nulls on (a), all passengers ----
    nulls, hist = {}, {"baseline": wbase}
    for s in (30, 60, 90, 120, -30, -60, -90, -120):
        nulls[f"shift{s:+d}s"], hist[f"shift{s:+d}s"] = full_metrics(shifted(tA, s), pax)
    nulls["direction_swap"], hist["direction_swap"] = full_metrics(swapped(tA), pax)
    for nm, fn in (("local_shuffle5", local_shuffle), ("random_timetable", random_tt), ("station_circular_shift", circ)):
        reps = [full_metrics(fn(tA, rng), pax) for _ in range(3)]
        hist[nm] = reps[0][1]
        keys = reps[0][0]["all"].keys()
        nulls[nm] = {b: {k: float(np.mean([r[0][b][k] for r in reps])) for k in keys} for b in reps[0][0]}
        nulls[nm + "_reps_all"] = [r[0]["all"] for r in reps]
    res["nulls_a"] = nulls
    # ---- EXPLORATORY (post hoc, after seeing the shift curve; not part of the frozen criteria) ----
    # Same nulls, but every timetable (baseline and nulls) is moved by the offset that minimised baseline neg share among tested shifts.
    shifts = {s: nulls[f"shift{s:+d}s"]["all"]["neg"] for s in (-30, -60, -90, -120)}
    best = min(shifts, key=shifts.get)
    ex = {"offset_s": best, "baseline": full_metrics(shifted(tA, best), pax)[0]["all"]}
    ex["direction_swap"] = full_metrics(shifted(swapped(tA), best), pax)[0]["all"]
    for nm, fn in (("local_shuffle5", local_shuffle), ("random_timetable", random_tt), ("station_circular_shift", circ)):
        reps = [full_metrics(shifted(fn(tA, rng), best), pax)[0]["all"] for _ in range(3)]
        ex[nm] = {k: float(np.mean([r[k] for r in reps])) for k in reps[0]}
    res["exploratory_shifted_nulls"] = ex
    # assigned-gap (X - 30 - A_x) distribution of the baseline: how close to the assignment edge do exits sit
    Pb = prep(tA); gaps = []
    for (lab, x), g in pax.groupby(["d", "x"]):
        gaps.append(preceding(Pb[lab], x, g.X.to_numpy())[1])
    gaps = np.concatenate(gaps); gaps = gaps[gaps <= MAXGAP]
    res["baseline_exit_gap_quantiles_s"] = dict(zip(("q05", "q25", "q50", "q75", "q95"), np.quantile(gaps, [.05, .25, .5, .75, .95]).tolist()),
                                                share_lt30=float((gaps < 30).mean()), share_lt60=float((gaps < 60).mean()))

    # ---- verdict against frozen criteria ----
    A = base["all"]
    chk = {"P1_assignable>=0.90": A["assignable"] >= .90, "P2_neg<=0.10": A["neg"] <= .10, "P3_window>=0.75": A["window"] >= .75,
           "P4_dir_match>=0.70": A["dir_match"] >= .70}
    chk["P5_band_neg<=0.15"] = all(base[b]["neg"] <= .15 for b in ("commute", "midday", "evening") if base[b]["n"] >= 1000)
    for nm in ("direction_swap", "local_shuffle5", "random_timetable", "station_circular_shift"):
        N = nulls[nm]["all"]
        chk[f"P6_{nm}_neg"] = (N["neg"] - A["neg"]) >= .10
        chk[f"P6_{nm}_window"] = (A["window"] - N["window"]) >= .10
        if nm != "local_shuffle5":
            chk[f"P6_{nm}_dir"] = (A["dir_match"] - N["dir_match"]) >= .10
    res["criteria_check"] = {k: bool(v) for k, v in chk.items()}
    res["passed_part1"] = bool(all(chk.values()))
    ca, cb = res["metrics_a_common_pax"]["all"], res["metrics_b_common_pax"]["all"]
    ha, hb = res["holdout"]["a_direct_anchor"]["recall"], res["holdout"]["b_strict"]["recall"]
    better = (ca["neg"] - cb["neg"] >= .02) and (cb["window"] - ca["window"] >= .02) and (hb - ha >= -.01)
    worse = (cb["neg"] - ca["neg"] >= .02 and ca["window"] - cb["window"] >= .02) or (ha - hb > .01)
    res["part2_verdict"] = "better" if better else ("worse" if worse else "no_clear_difference")
    (OUT / "direct_check_result.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")

    rows = []
    for tag, m in [("a_current", res["metrics_a_all_pax"])] + [(k, v) for k, v in nulls.items() if not k.endswith("_reps_all")]:
        for b, v in m.items():
            rows.append(dict(timetable=tag, band=b, **v))
    for tag, m in (("a_current_commonpax", res["metrics_a_common_pax"]), ("b_strict_commonpax", res["metrics_b_common_pax"])):
        for b, v in m.items():
            rows.append(dict(timetable=tag, band=b, **v))
    pd.DataFrame(rows).to_csv(OUT / "metrics.csv", index=False, float_format="%.4f")
    fig = {k: np.histogram(v, bins=np.arange(-600, 1201, 30))[0].tolist() for k, v in hist.items()}
    fig["bins"] = list(range(-600, 1171, 30))
    fig["baseline_b_common"] = np.histogram(wb, bins=np.arange(-600, 1201, 30))[0].tolist()
    (OUT / "fig_data.json").write_text(json.dumps(fig), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("facts", "TR_in_active", "reproduces_stack_csv_trains", "csv_trains", "max_abs_dev_vs_csv_s", "timetable_summary", "holdout", "passengers", "exploratory_shifted_nulls", "baseline_exit_gap_quantiles_s", "criteria_check", "passed_part1", "part2_verdict")}, indent=1, default=float, ensure_ascii=False))


if __name__ == "__main__":
    main()
