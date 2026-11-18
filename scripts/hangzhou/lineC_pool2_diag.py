"""Step 1 diagnosis (read-only) of: weekday toward_34 morning gaps (08:03 47min, 08:51 831s) and night ghost trains in the pooled weekday fit."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_pool as P
import lineC_stack as ST
from lineC_route_gate import build_topology, corridor_order, read_tags
import numpy as np, pandas as pd
from scipy.ndimage import gaussian_filter1d, uniform_filter1d
from scipy.stats import skew

OUT = P.OUT.parent / "lineC_pool2"
G0 = G1 = 0
WINS = []


def smooth_base(h):
    sm = gaussian_filter1d(h.astype(float), 10)
    return sm, uniform_filter1d(sm, ST.WIN, mode="constant") / ST.NORM


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gate, trips, _ = read_tags()
    tracks, membership, _, _, _ = build_topology(gate)
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate.get(s) == "C"]
    first, last = active[0], active[-1]
    DF = {d: P.load_day(d, first, last) for d in P.WEEKDAYS}
    pooled = pd.concat(DF.values(), ignore_index=True)
    st34 = active[::-1]; name34 = f"toward_{first}"
    res = {}
    # ---------- pooled fit ----------
    D = ST.build_direction(pooled, st34)
    refs, strength, adj, S = ST.pipeline(D["Z"], D["cum"], D["has"])
    global G0, G1, WINS
    off = D["cum"] + adj + ST.WALK
    g = np.diff(refs); sel = np.flatnonzero((refs[:-1] > 6 * 3600) & (refs[:-1] < 10 * 3600))
    i0 = sel[np.argmax(g[sel])]
    G0, G1 = int(refs[i0]) + 60, int(refs[i0 + 1]) - 60
    L = G1 - G0
    WINS = [("gap", (G0, G1)), ("ctrl_0630", (6 * 3600 + 1800, 6 * 3600 + 1800 + L)), ("ctrl_0930", (9 * 3600 + 1800, 9 * 3600 + 1800 + L)), ("ctrl_1100", (11 * 3600, 11 * 3600 + L))]
    res["gap_window_T0_seconds"] = [G0, G1]
    res["gap_window_T0_clock"] = [f"{G0 // 3600:02d}:{G0 % 3600 // 60:02d}", f"{G1 // 3600:02d}:{G1 % 3600 // 60:02d}"]
    # H2: exits in the train frame (tag time shifted back by the station offset) per minute per day, all stations pooled
    h2 = {}
    for lab, (lo, hi) in WINS:
        n = 0
        for k, st in enumerate(st34):
            t = pooled.loc[(pooled.direction == name34) & (pooled.exit_station == st), "exit_seconds"].to_numpy()
            n += int(((t >= lo + off[k]) & (t < hi + off[k])).sum())
        h2[lab] = n / len(DF) / ((hi - lo) / 60)
    res["H2_exits_per_min_per_day_train_frame"] = h2
    other = pooled[pooled.direction != name34]
    res["H2_other_direction_exits_per_min_per_day_same_clock"] = {lab: float(((other.exit_seconds >= lo) & (other.exit_seconds < hi)).sum() / len(DF) / ((hi - lo) / 60)) for lab, (lo, hi) in WINS}
    sub_gap = {st: int(((pooled.direction == name34) & (pooled.exit_station == st) & (pooled.exit_seconds >= G0 + off[k]) & (pooled.exit_seconds < G1 + off[k])).sum()) for k, st in enumerate(st34)}
    res["H2_gap_exits_per_station_per_day_total"] = {str(k): v / len(DF) for k, v in sub_gap.items()}
    baseS = uniform_filter1d(S, ST.WIN, mode="constant") / ST.NORM
    ratioS = S / np.maximum(baseS, 1e-12)
    # H1
    h1 = {}
    hist = {s: np.bincount(pooled.loc[(pooled.direction == name34) & (pooled.exit_station == s), "exit_seconds"].to_numpy(), minlength=ST.DAY) for s in st34}
    sb = {s: smooth_base(hist[s]) for s in st34}
    for lab, (lo, hi) in WINS:
        mx, frac, npk = [], [], []
        for k, s in enumerate(st34):
            sm, base = sb[s]
            a_, b_ = int(lo + off[k]), int(hi + off[k])
            r = sm[a_:b_] / np.maximum(base[a_:b_], 1e-9)
            mx.append(r.max()); frac.append((r >= 2.5).mean())
            npk.append(int(((D["pk"][k] >= lo + off[k] - ST.WALK) & (D["pk"][k] < hi + off[k] - ST.WALK)).sum()))
        h1[lab] = dict(median_station_max_ratio=float(np.median(mx)), median_share_seconds_ratio_ge_2_5=float(np.median(frac)),
                       median_peaks_per_station=float(np.median(npk)), peaks_by_station={str(s): npk[k] for k, s in enumerate(st34)},
                       expected_trains=float((hi - lo) / 290))
    res["H1_station_peak_ratio_pooled"] = h1
    for lab, (lo, hi) in WINS:
        res[f"stack_{lab}"] = dict(refs=int(((refs >= lo) & (refs < hi)).sum()), max_stack_ratio=float(ratioS[lo:hi].max()),
                                   median_stack_ratio=float(np.median(ratioS[lo:hi])), expected_trains=float((hi - lo) / 290))

    def sub_stack(ks):
        Sx = ST.stack([D["Z"][k] for k in ks], [D["cum"][k] + adj[k] + ST.WALK for k in ks])
        bx = uniform_filter1d(Sx, ST.WIN, mode="constant") / ST.NORM
        idx, _ = ST.find_peaks(Sx, distance=ST.STACK_DIST, height=ST.STACK_RATIO * bx)
        return {lab: int(((idx >= lo) & (idx < hi)).sum()) for lab, (lo, hi) in WINS}
    has = D["has"]
    res["stack_only_last8_stations_peaks"] = sub_stack(has[-8:])
    res["stack_only_first8_stations_peaks"] = sub_stack(has[:8])
    # ---------- H3 ----------
    perday, offs_all = [], []
    pooled_ok = refs[((refs < G0 - 600) | (refs > G1 + 600)) & (refs > 5.5 * 3600) & (refs < 22.5 * 3600)]
    for d, df in DF.items():
        Dd = ST.build_direction(df, st34)
        r_d, s_d, a_d, S_d = ST.pipeline(Dd["Z"], Dd["cum"], Dd["has"])
        b_d = uniform_filter1d(S_d, ST.WIN, mode="constant") / ST.NORM
        rr = S_d / np.maximum(b_d, 1e-12)
        sr = np.sort(r_d)
        j = np.clip(np.searchsorted(sr, pooled_ok), 1, len(sr) - 1)
        near = np.where(np.abs(sr[j - 1] - pooled_ok) <= np.abs(sr[j] - pooled_ok), sr[j - 1], sr[j])
        off = near - pooled_ok
        m = np.abs(off) <= 90
        offs_all.append(off[m])
        svc = sr[(sr > 6 * 3600) & (sr < 22 * 3600)]
        perday.append(dict(date=d, refs_in_gap=int(((r_d >= G0) & (r_d < G1)).sum()), max_stack_ratio_gap=float(rr[G0:G1].max()),
                           max_gap_s_06_22=float(np.diff(svc).max()), matched_share=float(m.mean()), off_median=float(np.median(off[m])), off_std=float(off[m].std())))
    res["H3_per_day"] = perday
    o = np.concatenate(offs_all)
    res["H3_offset_all_days_vs_pooled"] = dict(n=len(o), mean=float(o.mean()), std=float(o.std()), skew=float(skew(o)), q05=float(np.quantile(o, .05)),
                                                q25=float(np.quantile(o, .25)), q50=float(np.median(o)), q75=float(np.quantile(o, .75)), q95=float(np.quantile(o, .95)),
                                                share_pos=float((o > 0).mean()))
    res["H3_pooled_vs_single_gap_ratio"] = dict(pooled_max=float(ratioS[G0:G1].max()), single_day_max_median=float(np.median([p["max_stack_ratio_gap"] for p in perday])))
    # ---------- H4 ----------
    gh = refs < 4.5 * 3600
    real = (refs > 7 * 3600) & (refs < 22 * 3600)
    res["H4_ghost_stack_S"] = dict(ghost_S_median=float(np.median(S[refs[gh]])), ghost_S_max=float(S[refs[gh]].max()), ghost_base_median=float(np.median(baseS[refs[gh]])),
                                   ghost_ratio_median=float(np.median(ratioS[refs[gh]])), real_S_median=float(np.median(S[refs[real]])), real_S_q05=float(np.quantile(S[refs[real]], .05)),
                                   real_ratio_median=float(np.median(ratioS[refs[real]])))
    res["H4_pooled_refs_before_0430"] = int((refs < 4.5 * 3600).sum())
    res["H4_night_anchor_exits_before_0430_per_day_both_dirs"] = float((pooled.exit_seconds < 4.5 * 3600).sum() / len(DF))
    rows = []
    for tag, anchors in (("pooled18", pooled), ("single_0108", DF["2019-01-08"])):
        Dn = ST.build_direction(anchors, st34)
        r_n, _, _, _ = ST.pipeline(Dn["Z"], Dn["cum"], Dn["has"])
        below = []
        for s in st34:
            h = np.bincount(anchors.loc[(anchors.direction == name34) & (anchors.exit_station == s), "exit_seconds"].to_numpy(), minlength=ST.DAY)
            _, base = smooth_base(h)
            below.append(float((base[3600:4 * 3600] < ST.BASE_FLOOR).mean()))
        rows.append(dict(fit=tag, refs_before_0430=int((r_n < 4.5 * 3600).sum()), total_refs=int(len(r_n)),
                         mean_share_of_01_04_seconds_with_station_base_below_floor=float(np.mean(below))))
    res["H4_floor"] = rows
    old = ST.BASE_FLOOR
    ST.BASE_FLOOR = old * 18
    Dn = ST.build_direction(pooled, st34)
    r_n, _, _, _ = ST.pipeline(Dn["Z"], Dn["cum"], Dn["has"])
    ST.BASE_FLOOR = old
    res["H4_pooled_with_floor_x18"] = dict(refs_before_0430=int((r_n < 4.5 * 3600).sum()), total_refs=int(len(r_n)))
    (OUT / "diagnosis.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(perday).to_csv(OUT / "diag_per_day.csv", index=False, float_format="%.3f")
    short = {k: v for k, v in res.items() if k not in ("H3_per_day",)}
    for lab in list(short["H1_station_peak_ratio_pooled"]):
        short["H1_station_peak_ratio_pooled"][lab] = {k: v for k, v in short["H1_station_peak_ratio_pooled"][lab].items() if k != "peaks_by_station"}
    print(json.dumps(short, indent=1, default=float, ensure_ascii=False))


if __name__ == "__main__":
    main()
