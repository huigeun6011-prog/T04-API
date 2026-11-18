"""lineC_pos: positive control for the lineC_struct diagnostics (plant short-turns in an in-memory copy of the cached anchors). Rules: outputs/hangzhou/lineC_pos/criteria.md."""
import json, pickle
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_pool as P
import lineC_struct as S
from lineC_route_gate import build_topology, corridor_order, read_tags
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d

OUT = P.OUT.parent / "lineC_pos"
DAY, SEG, BANDS, EDGES, BLEN = S.DAY, S.SEG, S.BANDS, S.EDGES, S.BLEN
NULLR, RUSH = 2, (1, 3)
PS, FS, VARS, SEEDS = (13, 18, 23), (0.10, 0.25, 0.50), (0, 1), (1, 2)


def counts(Xv, day, d, posx, kmin, C, Cn, Xc, n, rng):
    m = posx >= kmin
    C[:, :, kmin:] = 0; Cn[:, :, :, kmin:] = 0; Xc[:, :, kmin:] = 0
    key = (day[m] * 2 + d[m]) * n + posx[m]
    df = pd.DataFrame(dict(key=key, t=np.clip(Xv[m].astype(int), 0, DAY - 1)))
    for k_, g in df.groupby("key"):
        i, di, k = k_ // (2 * n), (k_ // n) % 2, k_ % n
        h = np.bincount(g.t.to_numpy(), minlength=DAY)
        Xc[i, di, k] = np.histogram(g.t.to_numpy(), bins=EDGES)[0]
        C[i, di, k] = S.bandcount(S.peak_arr(h))
        lam = gaussian_filter1d(h.astype(float), 300)
        for r in range(NULLR):
            Cn[r, i, di, k] = S.bandcount(S.peak_arr(rng.poisson(np.clip(lam, 0, None))))


def e1_states(C, Cn, Xc, ntrain, n):
    nd = C.shape[0]
    L = np.array(BLEN) * nd
    rate = C.sum(0) / L
    nrate = Cn.sum(1).mean(0) / L
    Xs = Xc.sum(0) / nd
    ntr = np.zeros_like(rate); exc = np.zeros_like(rate)
    for di in (0, 1):
        for b in range(5):
            ntr[di, :, b] = Xs[di, :, b] / max(ntrain[di][b], 1)
            exc[di, :, b] = np.where(rate[di, :, b] > 0, (rate[di, :, b] - nrate[di, :, b]) / rate[di, :, b], -1)
    inf = (ntr >= S.NTR_MIN) & (exc >= S.EXCESS_MIN)
    e1 = np.empty((2, 5, 6), object)
    for di in (0, 1):
        for b in range(5):
            st = S.steps(rate[di, :, b], inf[di, :, b])
            for g, (a, z) in enumerate(SEG):
                ii = inf[di, a:z, b]
                if ii.sum() < 2 or st is None:
                    e1[di, b, g] = "unknown"; continue
                rd = (st["rho"][a:z][ii] <= S.RHO).mean()
                e1[di, b, g] = "reduced" if rd >= 0.6 else "normal" if rd <= 0.2 else "mixed"
    return e1


def e23(Nn, bidx, rng):
    nd, _, n = Nn[0].shape
    e2 = np.zeros((2, 5, 6)); e2n = np.zeros((2, 5, 6)); pr = np.zeros((2, 5, 6)); ab = np.zeros((2, 5, 6)); un = np.zeros((2, 5, 6))
    for di in (0, 1):
        N = Nn[di]

        def repro(Nx):
            typ = np.full((N.shape[1], n), np.nan)
            for b in range(5):
                ix = bidx[di] == b
                if ix.any():
                    typ[ix] = Nx[:, ix, :].mean((0, 1))
            cand = (Nx >= 2.5 * typ[None]) & (typ[None] >= 8)
            for j in (1, 2, 3):
                tj = np.roll(typ, -j, axis=1)[None]
                cand &= (np.roll(Nx, -j, axis=2) <= 0.2 * tj) & (tj >= 8)
            cand[:, :, n - 5:] = False
            return cand.sum(0) >= 6
        rep = repro(N)
        nulls = []
        for _ in range(2):
            Nx = N.copy()
            for b in range(5):
                ix = np.flatnonzero(bidx[di] == b)
                if len(ix) < 2:
                    continue
                for i in range(nd):
                    for k in range(n):
                        Nx[i, ix, k] = N[i, rng.permutation(ix), k]
            nulls.append(repro(Nx))
        tot = N.sum(0)
        for b in range(5):
            ix = np.flatnonzero(bidx[di] == b)
            if len(ix) == 0:
                continue
            obs = np.column_stack([tot[ix][:, a:z].sum(1) for a, z in SEG])
            typg = obs.mean(0)
            present = (obs >= 0.5 * typg) & (obs >= 30)
            absent = (obs <= 0.1 * typg) & (typg >= 100)
            for g, (a, z) in enumerate(SEG):
                e2[di, b, g] = rep[ix][:, a:z].any(1).mean()
                e2n[di, b, g] = np.mean([m[ix][:, a:z].any(1).mean() for m in nulls])
                pr[di, b, g] = present[:, g].mean(); ab[di, b, g] = absent[:, g].mean(); un[di, b, g] = (~present[:, g] & ~absent[:, g]).mean()
    return e2, e2n, pr, ab, un


def verdicts(e1, e2, e2n, pr, ab):
    V = np.empty((2, 5, 6), object)
    for di in (0, 1):
        for b in range(5):
            for g in range(6):
                prev = g > 0 and e2[di, b, g - 1] >= 0.05 and e2[di, b, g - 1] >= 2 * e2n[di, b, g - 1]
                sup = e1[di, b, g] == "reduced" and (ab[di, b, g] >= 0.15 or prev)
                ref = e1[di, b, g] == "normal" and pr[di, b, g] >= 0.85
                V[di, b, g] = "지원" if sup else "반박" if ref else "알 수 없음"
    return V


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gate, trips, _ = read_tags()
    tracks, membership, _, _, _ = build_topology(gate)
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate.get(s) == "C"]
    first, last = active[0], active[-1]
    pk = pickle.load(open(P.CACHE / "pool3_final.pkl", "rb"))
    tabs, Lo = pk["tabs"], pk["Lo"]
    days = pk["days"]
    n = len(active)
    DF = {d: P.load_day(d, first, last) for d in days}
    anchors = pd.concat([DF[d] for d in days], ignore_index=True)
    dayidx = np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(days)])
    ps = P.PaxSet(anchors, active, dayidx)
    dnames = [f"toward_{first}", f"toward_{last}"]
    order = {0: active[::-1], 1: active}
    # assignment (before modification)
    Pp = P.prep(tabs)
    tr = np.full(ps.n, -1)
    for (di, x), idx in ps.gdx.items():
        lab = dnames[di]; t = Pp[lab]; k = t["col"][x]
        v = t["vals"][:, k] + Lo[lab][k]
        j = np.searchsorted(v, ps.X[idx], side="right") - 1
        gap = np.where(j >= 0, ps.X[idx] - v[np.clip(j, 0, None)], np.inf)
        tr[idx] = np.where(gap <= 600, t["order"][np.clip(j, 0, None), k], -1)
    posmap = {di: np.full(100, -1) for di in (0, 1)}
    for di in (0, 1):
        for k, s in enumerate(order[di]):
            posmap[di][s] = k
    posx = np.where(ps.d == 0, posmap[0][ps.x], posmap[1][ps.x])
    pose = np.where(ps.d == 0, posmap[0][ps.e], posmap[1][ps.e])
    ntr = {di: len(tabs[dnames[di]]["arr"]) for di in (0, 1)}
    bidx, ntrain = {}, {}
    for di in (0, 1):
        b = np.digitize(tabs[dnames[di]]["arr"][:, 0], EDGES) - 1
        bidx[di] = np.where((b >= 0) & (b < 5), b, -1)
        ntrain[di] = np.array([(bidx[di] == j).sum() for j in range(5)])
    nd = len(days)

    def Ncounts(keep, posx2):
        out = {}
        for di in (0, 1):
            m = keep & (ps.d == di) & (tr >= 0)
            flat = (ps.day[m] * ntr[di] + tr[m]) * n + posx2[m]
            out[di] = np.bincount(flat, minlength=nd * ntr[di] * n).reshape(nd, ntr[di], n).astype(float)
        return out
    rng0 = np.random.default_rng(20190108)
    C0 = np.zeros((nd, 2, n, 5)); Cn0 = np.zeros((NULLR, nd, 2, n, 5)); X0 = np.zeros((nd, 2, n, 5))
    counts(ps.X, ps.day, ps.d, posx, 0, C0, Cn0, X0, n, rng0)
    print("baseline counts done", flush=True)

    def diagnose(C, Cn, Xc, N, rng):
        e1 = e1_states(C, Cn, Xc, ntrain, n)
        e2, e2n, pr, ab, un = e23(N, bidx, rng)
        return e1, e2, e2n, pr, ab, un, verdicts(e1, e2, e2n, pr, ab)
    base = diagnose(C0, Cn0, X0, Ncounts(np.ones(ps.n, bool), posx), rng0)
    Vb = base[6]
    cell_rows = []
    for di in (0, 1):
        for b in range(5):
            for g in range(6):
                cell_rows.append(dict(scenario="baseline", direction=dnames[di], band=BANDS[b][0], seg=g, e1=base[0][di, b, g], e2_share=base[1][di, b, g], e3_present=base[3][di, b, g],
                                      e3_absent=base[4][di, b, g], verdict=Vb[di, b, g]))
    res = {"baseline_verdict_counts": pd.Series(Vb.ravel()).value_counts().to_dict(),
           "baseline_e1_counts": pd.Series(base[0].ravel()).value_counts().to_dict()}
    sc_rows, ctrl_rows = [], []
    scen = [(0, 0.0, 0, s) for s in SEEDS] + [(p, f, v, s) for p in PS for f in FS for v in VARS for s in SEEDS]
    for (p, f, var, seed) in scen:
        r = np.random.default_rng(20190108 + 1000 * seed + 10 * p + int(100 * f) + var)
        sel = {di: np.zeros(ntr[di], bool) for di in (0, 1)}
        for di in (0, 1):
            for b in RUSH:
                ix = np.flatnonzero(bidx[di] == b)
                k = int(round(f * len(ix)))
                if k:
                    sel[di][r.choice(ix, k, replace=False)] = True
        trc = np.clip(tr, 0, None)
        selp = np.where(ps.d == 0, sel[0][np.clip(trc, 0, ntr[0] - 1)], sel[1][np.clip(trc, 0, ntr[1] - 1)]) & (tr >= 0)
        beyond = selp & (posx > p) if f > 0 else np.zeros(ps.n, bool)
        keep = ~beyond
        X2, posx2 = ps.X.copy(), posx.copy()
        if var == 1 and f > 0:
            mv = beyond & (pose < p)
            for di in (0, 1):
                m = mv & (ps.d == di)
                X2[m] = tabs[dnames[di]]["arr"][tr[m], p] + Lo[dnames[di]][p] + r.uniform(0, 60, m.sum())
                posx2[m] = p
            keep = keep | mv
        kmin = p if f > 0 else n
        C, Cn, Xc = C0.copy(), Cn0.copy(), X0.copy()
        if f > 0:
            counts(X2[keep], ps.day[keep], ps.d[keep], posx2[keep], kmin, C, Cn, Xc, n, r)
        out = diagnose(C, Cn, Xc, Ncounts(keep, posx2), r)
        e1, e2, e2n, pr, ab, un, V = out
        for di in (0, 1):
            for b in range(5):
                for g in range(6):
                    cell_rows.append(dict(scenario=f"p{p}_f{f}_v{var}_s{seed}", p=p, f=f, variant=var, seed=seed, direction=dnames[di], band=BANDS[b][0], seg=g,
                                          affected=bool(f > 0 and b in RUSH and SEG[g][0] > p), baseline_e1=base[0][di, b, g], e1=e1[di, b, g], e2_share=e2[di, b, g],
                                          e3_present=pr[di, b, g], e3_absent=ab[di, b, g], verdict=V[di, b, g], baseline_verdict=Vb[di, b, g]))
        print("scenario", p, f, var, seed, flush=True)
    CR = pd.DataFrame(cell_rows)
    CR.to_csv(OUT / "pos_cells.csv", index=False, float_format="%.3f")
    # ---------- detection table ----------
    S_ = CR[CR.scenario != "baseline"]
    rows = []
    for (p, f, var), g in S_[S_.f > 0].groupby(["p", "f", "variant"]):
        aff = g[g.affected]
        inf = aff[aff.baseline_e1 != "unknown"]
        segp = [i for i, (a, z) in enumerate(SEG) if a <= p < z][0]
        e2c = g[(g.seg == segp) & g.band.isin([BANDS[b][0] for b in RUSH])]
        rows.append(dict(p=p, f=f, variant=var, affected_cells=len(aff) // len(SEEDS), informative_affected_cells=len(inf) // len(SEEDS),
                         det_synthesis_informative=float((inf.verdict == "지원").mean()) if len(inf) else np.nan, det_synthesis_all_affected=float((aff.verdict == "지원").mean()),
                         det_E1_reduced=float((inf.e1 == "reduced").mean()) if len(inf) else np.nan, det_E3_absent_ge_015=float((aff.e3_absent >= 0.15).mean()),
                         det_E2_supportive_at_turn_segment=float(((e2c.e2_share >= 0.05)).mean()) if var == 1 else np.nan,
                         reliable=bool(len(inf) and (inf.verdict == "지원").mean() >= 0.70)))
    DT = pd.DataFrame(rows)
    DT.to_csv(OUT / "detection_by_scenario.csv", index=False, float_format="%.3f")
    ctrl = S_[S_.f == 0]
    res["control_false_support_share_all_60"] = float((ctrl.verdict == "지원").mean())
    res["control_verdicts"] = ctrl.verdict.value_counts().to_dict()
    # ---------- refutation re-interpretation ----------
    ref_rows = []
    bcells = CR[(CR.scenario == "baseline") & (CR.verdict == "반박")]
    for _, c in bcells.iterrows():
        row = dict(direction=c.direction, band=c.band, seg=c.seg)
        for f in FS:
            sub = S_[(S_.f == f) & (S_.direction == c.direction) & (S_.band == c.band) & (S_.seg == c.seg) & S_.affected]
            row[f"changed_from_refute_share_f{f}"] = float((sub.verdict != "반박").mean()) if len(sub) else np.nan
        ok = [f for f in FS if row[f"changed_from_refute_share_f{f}"] >= 0.70]
        row["min_detectable_f"] = min(ok) if ok else None
        ref_rows.append(row)
    RF = pd.DataFrame(ref_rows)
    RF.to_csv(OUT / "refutation_reliability.csv", index=False, float_format="%.3f")
    res["detection_table"] = DT.round(3).to_dict("records")
    res["refutation_cells"] = int(len(RF))
    res["refutation_min_detectable_f_counts"] = RF.min_detectable_f.fillna(-1).value_counts().to_dict()
    res["unknown_cells_baseline_by_band"] = {b[0]: int(((CR.scenario == "baseline") & (CR.band == b[0]) & (CR.verdict == "알 수 없음")).sum()) for b in BANDS}
    (OUT / "pos_metrics.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "detection_table"}, indent=1, default=float, ensure_ascii=False))
    print(DT.round(2).to_string())


if __name__ == "__main__":
    main()
