"""lineC_struct: evidence for/against short-turn (mid-line start/terminate) trains on weekdays. Rules: outputs/hangzhou/lineC_struct/criteria.md (frozen)."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_pool as P
import lineC_pool2 as P2
import lineC_stack as ST
from lineC_route_gate import build_topology, corridor_order, read_tags
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d, uniform_filter1d
from scipy.signal import find_peaks, peak_widths

OUT = P.OUT.parent / "lineC_struct"
DAY = 86400
BANDS = [("05-07", 5, 7), ("07-09", 7, 9), ("09-17", 9, 17), ("17-19", 17, 19), ("19-23:30", 19, 23.5)]
EDGES = [b[1] * 3600 for b in BANDS] + [BANDS[-1][2] * 3600]
BLEN = [b[2] - b[1] for b in BANDS]
NTR_MIN, EXCESS_MIN, RHO, RUN, NB, NULL_REPS = 8, 0.5, 0.67, 3, 300, 8
SEG = [(0, 6), (6, 11), (11, 16), (16, 21), (21, 26), (26, 32)]
rng = np.random.default_rng(20190108)


def peak_arr(h):
    if h.sum() == 0:
        return np.empty(0)
    sm = gaussian_filter1d(h.astype(float), 10)
    base = uniform_filter1d(sm, ST.WIN, mode="constant") / ST.NORM
    idx, pr = find_peaks(sm, distance=45, height=2.5 * base, prominence=(None, None))
    if len(idx) == 0:
        return np.empty(0)
    _, _, left, _ = peak_widths(sm, idx, prominence_data=(pr["prominences"], pr["left_bases"], pr["right_bases"]))
    a = left - 30
    return a[(a >= 0) & (a < DAY)]


def bandcount(a):
    return np.histogram(a, bins=EDGES)[0]


def steps(rate, inf):
    mid = [k for k in range(11, 21) if inf[k]]
    if len(mid) < 3 or np.median(rate[mid]) <= 0:
        return None
    rho = rate / np.median(rate[mid])
    out = {}
    n = len(rate)
    for end, order in (("head", range(n)), ("tail", range(n - 1, -1, -1))):
        run = []
        for k in order:
            if not inf[k]:
                continue
            if rho[k] <= RHO:
                run.append(k)
            else:
                break
        out[end] = dict(found=len(run) >= RUN, run=run, cp=(run[-1] if run else None), mag=float(np.median(rho[run])) if run else np.nan)
    out["rho"] = rho
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gate, trips, _ = read_tags()
    tracks, membership, _, _, _ = build_topology(gate)
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate.get(s) == "C"]
    first, last = active[0], active[-1]
    days = P.WEEKDAYS
    nd = len(days)
    DF = {d: P.load_day(d, first, last) for d in days}
    dnames = [f"toward_{first}", f"toward_{last}"]          # dir 0 = toward_34 (order 66..34), dir 1 = toward_66 (order 34..66)
    order = {0: active[::-1], 1: active}
    n = len(active)
    # ---------- E1: independent peaks ----------
    C = np.zeros((nd, 2, n, 5)); X = np.zeros((nd, 2, n, 5)); Cn = np.zeros((NULL_REPS, nd, 2, n, 5))
    for i, d in enumerate(days):
        for di in (0, 1):
            sub = DF[d][DF[d].direction == dnames[di]]
            for s, g in sub.groupby("exit_station"):
                k = order[di].index(s)
                t = g.exit_seconds.to_numpy()
                h = np.bincount(t, minlength=DAY)
                X[i, di, k] = np.histogram(t, bins=EDGES)[0]
                C[i, di, k] = bandcount(peak_arr(h))
                lam = gaussian_filter1d(h.astype(float), 300)
                for r in range(NULL_REPS):
                    Cn[r, i, di, k] = bandcount(peak_arr(rng.poisson(np.clip(lam, 0, None))))
        print("peaks day", d, flush=True)
    # ---------- pool2 timetable + assignment ----------
    ST.find_refs = P2.find_refs2
    for d in days:
        P2.DAYREFS[d] = P2.day_refs_cache(d, DF[d], active)
    anchors, dirs, tabs, info, fr = P2.build_pool2(days, DF, active, True)
    dayidx = np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(days)])
    ps = P.PaxSet(anchors, active, dayidx)
    Lo, Li, _ = P.fit_lags(tabs, ps, active)
    Pp = P.prep(tabs)
    lab_of = {0: dnames[0], 1: dnames[1]}
    tr = np.full(ps.n, -1)
    for (di, x), idx in ps.gdx.items():
        lab = lab_of[di]; t = Pp[lab]; k = t["col"][x]
        v = t["vals"][:, k] + Lo[lab][k]
        j = np.searchsorted(v, ps.X[idx], side="right") - 1
        gap = np.where(j >= 0, ps.X[idx] - v[np.clip(j, 0, None)], np.inf)
        tr[idx] = np.where(gap <= 600, t["order"][np.clip(j, 0, None), k], -1)
    Nn, bidx, ntrain = {}, {}, {}
    for di in (0, 1):
        lab = lab_of[di]; ntr = len(tabs[lab]["arr"])
        assert tabs[lab]["stations"] == order[di]
        m = (ps.d == di) & (tr >= 0)
        flat = (ps.day[m] * ntr + tr[m]) * n + Pp[lab]["col"][ps.x[m]]
        Nn[di] = np.bincount(flat, minlength=nd * ntr * n).reshape(nd, ntr, n).astype(float)
        t0 = tabs[lab]["arr"][:, 0]
        b = np.digitize(t0, EDGES) - 1
        bidx[di] = np.where((b >= 0) & (b < 5), b, -1)
        ntrain[di] = np.array([(bidx[di] == j).sum() for j in range(5)])
    # ---------- E1 analysis ----------
    Cs, Cns = C.sum(0), Cn.sum(1)                 # (dir,n,band), (rep,dir,n,band)
    Xs = X.sum(0) / nd
    L = np.array(BLEN) * nd
    rate = Cs / L; null_rate = Cns.mean(0) / L
    ntr_cell = np.zeros_like(rate); excess = np.zeros_like(rate); inf = np.zeros(rate.shape, bool)
    for di in (0, 1):
        for b in range(5):
            ntr_cell[di, :, b] = Xs[di, :, b] / max(ntrain[di][b], 1)
            excess[di, :, b] = np.where(rate[di, :, b] > 0, (rate[di, :, b] - null_rate[di, :, b]) / rate[di, :, b], -1)
    inf = (ntr_cell >= NTR_MIN) & (excess >= EXCESS_MIN)
    cells = []
    prof = {}
    for di in (0, 1):
        for b in range(5):
            st = steps(rate[di, :, b], inf[di, :, b])
            prof[(di, b)] = st
            for k in range(n):
                cells.append(dict(direction=dnames[di], band=BANDS[b][0], pos=k, stationID=int(order[di][k]), peaks_per_hour=rate[di, k, b],
                                  headway_s=3600 / rate[di, k, b] if rate[di, k, b] > 0 else np.nan, null_peaks_per_hour=null_rate[di, k, b],
                                  excess=excess[di, k, b], exits_per_train=ntr_cell[di, k, b], informative=bool(inf[di, k, b]),
                                  rho=float(st["rho"][k]) if st else np.nan))
    pd.DataFrame(cells).to_csv(OUT / "e1_headway_by_station.csv", index=False, float_format="%.4f")
    cprows = []
    for di in (0, 1):
        for b in range(5):
            for end in ("head", "tail"):
                st = prof[(di, b)]
                found_b, cps = 0, []
                for _ in range(NB):
                    ii = rng.integers(0, nd, nd)
                    sb = steps(C[ii].sum(0)[di, :, b] / L[b], inf[di, :, b])
                    if sb and sb[end]["found"]:
                        found_b += 1; cps.append(sb[end]["cp"])
                fs = 0
                for r in range(NULL_REPS):
                    sn = steps(Cn[r].sum(0)[di, :, b] / L[b], inf[di, :, b])
                    fs += int(bool(sn and sn[end]["found"]))
                cprows.append(dict(direction=dnames[di], band=BANDS[b][0], end=end, evaluable=st is not None,
                                   informative_stations_in_end_3=int(inf[di, :3, b].sum() if end == "head" else inf[di, -3:, b].sum()),
                                   step_found=bool(st and st[end]["found"]), run_len=len(st[end]["run"]) if st else 0,
                                   changepoint_pos=st[end]["cp"] if st and st[end]["found"] else None,
                                   changepoint_station=int(order[di][st[end]["cp"]]) if st and st[end]["found"] else None,
                                   magnitude_rho=st[end]["mag"] if st else np.nan, boot_found_share=found_b / NB,
                                   boot_cp_lo=float(np.quantile(cps, .05)) if cps else np.nan, boot_cp_hi=float(np.quantile(cps, .95)) if cps else np.nan,
                                   null_false_step_share=fs / NULL_REPS))
    CP = pd.DataFrame(cprows)
    CP.to_csv(OUT / "e1_changepoints.csv", index=False, float_format="%.3f")
    # ---------- E2 / E3 ----------
    def e2_repro(N, di, shuffle):
        N = N.copy()
        if shuffle:
            for b in range(5):
                idx = np.flatnonzero(bidx[di] == b)
                for i in range(nd):
                    for k in range(n):
                        N[i, idx, k] = N[i, rng.permutation(idx), k]
        typ = np.full((len(bidx[di]), n), np.nan)
        for b in range(5):
            idx = bidx[di] == b
            if idx.any():
                typ[idx] = N[:, idx, :].mean((0, 1))
        cand = (N >= 2.5 * typ[None]) & (typ[None] >= 8)
        for j in (1, 2, 3):
            tj = np.roll(typ, -j, axis=1)[None]
            cand &= (np.roll(N, -j, axis=2) <= 0.2 * tj) & (tj >= 8)
        cand[:, :, n - 5:] = False
        return cand.sum(0) >= 6, typ
    seg_rows, e2_list, e3_train = [], [], []
    res = {}
    for di in (0, 1):
        N = Nn[di]
        rep, typ = e2_repro(N, di, False)
        nulls = [e2_repro(N, di, True)[0] for _ in range(5)]
        tot = N.sum(0)                                  # train x station (18 days)
        for g, (a, z) in enumerate(SEG):
            pass
        for b in range(5):
            idx = np.flatnonzero(bidx[di] == b)
            if len(idx) == 0:
                continue
            obs = np.column_stack([tot[idx][:, a:z].sum(1) for a, z in SEG])
            typg = obs.mean(0)
            present = (obs >= 0.5 * typg) & (obs >= 30)
            absent = (obs <= 0.1 * typg) & (typg >= 100)
            for ti, t in enumerate(idx):
                pres_seg = np.flatnonzero(present[ti])
                lastp = pres_seg.max() if len(pres_seg) else -1
                later_abs = absent[ti, lastp + 1:].any() if lastp >= 0 else False
                later_pres = False
                cand = bool(lastp >= 0 and lastp < len(SEG) - 1 and later_abs and not present[ti, lastp + 1:].any())
                e3_train.append(dict(direction=dnames[di], band=BANDS[b][0], train=int(t), last_present_seg=int(lastp), turnback_candidate=cand,
                                     **{f"obs_seg{g}": float(obs[ti, g]) for g in range(6)}, **{f"state_seg{g}": ("present" if present[ti, g] else "absent" if absent[ti, g] else "unknown") for g in range(6)}))
            for g, (a, z) in enumerate(SEG):
                e1i = inf[di, a:z, b]
                if e1i.sum() < 2:
                    e1s = "unknown"
                else:
                    rd = (prof[(di, b)]["rho"][a:z][e1i] <= RHO).mean() if prof[(di, b)] else np.nan
                    e1s = "unknown" if np.isnan(rd) else "reduced" if rd >= 0.6 else "normal" if rd <= 0.2 else "mixed"
                e2 = float(rep[idx][:, a:z].any(1).mean())
                e2n = float(np.mean([m[idx][:, a:z].any(1).mean() for m in nulls]))
                e3 = dict(present=float(present[:, g].mean()), absent=float(absent[:, g].mean()), unknown=float((~present[:, g] & ~absent[:, g]).mean()))
                seg_rows.append(dict(direction=dnames[di], band=BANDS[b][0], seg=g, seg_pos=f"{a}-{z - 1}", trains=int(len(idx)), e1=e1s, e2_share=e2, e2_null_share=e2n,
                                     e3_present=e3["present"], e3_absent=e3["absent"], e3_unknown=e3["unknown"], typ_exits_18d=float(typg[g])))
                for ti, t in enumerate(idx):
                    for k in range(a, z):
                        if rep[t, k]:
                            e2_list.append(dict(direction=dnames[di], band=BANDS[b][0], train=int(t), pos=k, stationID=int(order[di][k]), days_flagged=int(((N[:, t, k] >= 2.5 * typ[t, k])).sum())))
    S = pd.DataFrame(seg_rows)
    sup, ref, lab = [], [], []
    for i, r in S.iterrows():
        prev = S[(S.direction == r.direction) & (S.band == r.band) & (S.seg == r.seg - 1)]
        e2prev = bool(len(prev) and prev.e2_share.iloc[0] >= 0.05 and prev.e2_share.iloc[0] >= 2 * prev.e2_null_share.iloc[0])
        e2self = bool(r.e2_share >= 0.05 and r.e2_share >= 2 * r.e2_null_share)
        s = r.e1 == "reduced" and (r.e3_absent >= 0.15 or e2prev)
        f = r.e1 == "normal" and r.e3_present >= 0.85
        lab.append("지원" if s else "반박" if f else "알 수 없음")
    S["verdict"] = lab
    S.to_csv(OUT / "synthesis_by_segment.csv", index=False, float_format="%.3f")
    pd.DataFrame(e2_list).to_csv(OUT / "e2_turnback_candidates.csv", index=False)
    pd.DataFrame(e3_train).to_csv(OUT / "e3_train_segments.csv", index=False, float_format="%.1f")
    # ---------- summaries ----------
    res["synthesis_counts_all"] = S.verdict.value_counts().to_dict()
    res["synthesis_counts_by_band"] = {b: S[S.band == b].verdict.value_counts().to_dict() for b, _, _ in BANDS}
    res["synthesis_counts_rush"] = S[S.band.isin(["07-09", "17-19"])].verdict.value_counts().to_dict()
    E3 = pd.DataFrame(e3_train)
    res["e3_turnback_candidate_share_by_dir_band"] = E3.groupby(["direction", "band"]).turnback_candidate.mean().round(3).reset_index().to_dict("records")
    res["e1_changepoints_found"] = CP[CP.step_found][["direction", "band", "end", "changepoint_station", "magnitude_rho", "boot_found_share", "null_false_step_share"]].to_dict("records")
    res["e1_evaluable_share"] = float(CP.evaluable.mean())
    res["null_false_step_share_mean"] = float(CP[CP.evaluable].null_false_step_share.mean())
    res["informative_cell_share_by_band"] = {BANDS[b][0]: float(inf[:, :, b].mean()) for b in range(5)}
    res["pool2_headway_mean_s"] = P2.gap_metrics(tabs)
    res["morning_0709_independent_peak_headway_s"] = {}
    for di in (0, 1):
        r_ = rate[di, :, 1]; ok = inf[di, :, 1]
        res["morning_0709_independent_peak_headway_s"][dnames[di]] = {
            f"seg{g}": (float(np.median(3600 / r_[a:z][ok[a:z] & (r_[a:z] > 0)])) if (ok[a:z] & (r_[a:z] > 0)).any() else None) for g, (a, z) in enumerate(SEG)}
    res["morning_0709_trains_per_day_pool2"] = {dnames[di]: int(ntrain[di][1]) for di in (0, 1)}
    br = {}
    for di in (0, 1):
        for end, sl in (("head", slice(0, 6)), ("tail", slice(26, 32))):
            vals = []
            for b in range(5):
                st = prof[(di, b)]
                if st is None:
                    vals.append(None); continue
                ok = inf[di, sl, b]
                vals.append(float(np.median(st["rho"][sl][ok])) if ok.any() else None)
            br[f"{dnames[di]}_{end}"] = dict(zip([b[0] for b in BANDS], vals))
    res["end_segment_median_rho_by_band"] = br
    (OUT / "struct_metrics.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=1, default=float, ensure_ascii=False)[:10000])


if __name__ == "__main__":
    main()
