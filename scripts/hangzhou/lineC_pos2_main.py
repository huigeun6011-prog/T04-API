"""Runner for lineC_pos2 (new synthesis rule, scenarios, final timetable file). Rules frozen in outputs/hangzhou/lineC_pos2/criteria.md and lineC_final/criteria.md."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import lineC_pool as P
from lineC_pos2 import (BANDS, EDGES, FIN, OUT, RUSH, SEG, Ncounts, e23, setup, verdicts2)

PS_, FS_, SEEDS_ = (13, 18, 23), (0.10, 0.25, 0.50), (1, 2, 3, 4)


def run_scenarios(c, zone):
    ps, tr, tabs, Lo = c["ps"], c["tr"], c["tabs"], c["Lo"]
    ntr, dn = c["ntr"], c["dnames"]
    rows = []
    scen = [(0, 0.0, 0, s) for s in SEEDS_] + [(p, f, v, s) for p in PS_ for f in FS_ for v in (0, 1) for s in SEEDS_]
    for (p, f, var, seed) in scen:
        r = np.random.default_rng(20190108 + 1000 * seed + 10 * p + int(100 * f) + var)
        sel = {di: np.zeros(ntr[di], bool) for di in (0, 1)}
        for di in (0, 1):
            for b in RUSH:
                ix = np.flatnonzero(c["bidx"][di] == b)
                k = int(round(f * len(ix)))
                if k:
                    sel[di][r.choice(ix, k, replace=False)] = True
        trc = np.clip(tr, 0, None)
        selp = np.where(ps.d == 0, sel[0][np.clip(trc, 0, ntr[0] - 1)], sel[1][np.clip(trc, 0, ntr[1] - 1)]) & (tr >= 0)
        beyond = selp & (c["posx"] > p) if f > 0 else np.zeros(ps.n, bool)
        keep = ~beyond
        posx2 = c["posx"].copy()
        if var == 1 and f > 0:
            mv = beyond & (c["pose"] < p)
            for di in (0, 1):
                m = mv & (ps.d == di)
                posx2[m] = p
                r.uniform(0, 60, m.sum())   # keeps the rng stream identical to lineC_pos (the time itself is unused by E2/E3)
            keep = keep | mv
        e2, e2n, pr, ab, typ = e23(Ncounts(c, keep, posx2), c["bidx"], r)
        V = verdicts2(e2, e2n, pr, ab, typ, zone)
        for di in (0, 1):
            for b in range(5):
                for g in range(6):
                    rows.append(dict(p=p, f=f, variant=var, seed=seed, direction=dn[di], band=BANDS[b][0], seg=g, affected=bool(f > 0 and b in RUSH and SEG[g][0] > p),
                                     e2_share=e2[di, b, g], e2_null=e2n[di, b, g], e3_present=pr[di, b, g], e3_absent=ab[di, b, g], typ=typ[di, b, g], verdict=V[di, b, g]))
        print("scenario", p, f, var, seed, flush=True)
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    FIN.mkdir(parents=True, exist_ok=True)
    c = setup()
    ps, dn = c["ps"], c["dnames"]
    rng0 = np.random.default_rng(20190108)
    N0 = Ncounts(c, np.ones(ps.n, bool), c["posx"])
    e2, e2n, pr, ab, typ = e23(N0, c["bidx"], rng0)
    zone = np.zeros((2, 5), bool)
    zrows = []
    for di in (0, 1):
        for b in range(5):
            ix = np.flatnonzero(c["bidx"][di] == b)
            ptd = float(np.median(N0[di][:, ix, :].sum(2)))
            infshare = float((typ[di, b] >= 100).mean())
            zone[di, b] = ptd >= 350 and infshare >= 0.5
            zrows.append(dict(direction=dn[di], band=BANDS[b][0], trains=len(ix), median_exits_per_train_per_day=ptd, informative_seg_share=infshare, in_zone=bool(zone[di, b])))
    pd.DataFrame(zrows).to_csv(OUT / "analysis_zone.csv", index=False, float_format="%.3f")
    tr_in = sum(len(np.flatnonzero(c["bidx"][di] == b)) for di in (0, 1) for b in range(5) if zone[di, b])
    tr_all = sum(c["ntr"].values())
    bnd = np.digitize(ps.X, EDGES) - 1
    inz = np.zeros(ps.n, bool)
    for di in (0, 1):
        for b in range(5):
            if zone[di, b]:
                inz |= (ps.d == di) & (bnd == b)
    cov = dict(trains_in_zone=int(tr_in), trains_total=int(tr_all), trains_share=tr_in / tr_all, anchors_share=float(inz.mean()), anchors_total=int(ps.n),
               anchors_outside_05_2330=float(((bnd < 0) | (bnd > 4)).mean()))
    V0 = verdicts2(e2, e2n, pr, ab, typ, zone)
    B = []
    for di in (0, 1):
        for b in range(5):
            for g in range(6):
                B.append(dict(direction=dn[di], band=BANDS[b][0], seg=g, seg_pos=f"{SEG[g][0]}-{SEG[g][1] - 1}", in_zone=bool(zone[di, b]), typ=typ[di, b, g], e3_present=pr[di, b, g],
                              e3_absent=ab[di, b, g], e2_share=e2[di, b, g], e2_null=e2n[di, b, g], verdict=V0[di, b, g]))
    BT = pd.DataFrame(B)
    BT.to_csv(OUT / "baseline_verdict_60cells.csv", index=False, float_format="%.3f")
    CR = run_scenarios(c, zone)
    CR.to_csv(OUT / "pos2_cells.csv", index=False, float_format="%.3f")
    key = BT[["direction", "band", "seg", "typ", "in_zone", "verdict"]].rename(columns={"typ": "base_typ", "verdict": "base_verdict"})
    CR = CR.merge(key, on=["direction", "band", "seg"])
    ctrl = CR[CR.f == 0]
    zc = ctrl[ctrl.in_zone]
    res = dict(coverage=cov, baseline_verdict_counts=BT.verdict.value_counts().to_dict(),
               false_support=dict(seeds=4, cells_per_seed_in_zone=int(len(zc) // 4), cell_runs=int(len(zc)), support_runs=int((zc.verdict == "지원").sum()), share=float((zc.verdict == "지원").mean())))
    rows = []
    for (p, f, var), g in CR[CR.f > 0].groupby(["p", "f", "variant"]):
        aff = g[g.affected & (g.base_typ >= 100) & g.in_zone]
        per = aff.groupby("seed").verdict.apply(lambda x: (x == "지원").mean())
        affall = g[g.affected]
        e2c = ((affall.e2_share >= 0.05) & (affall.e2_share >= 2 * affall.e2_null)).mean()
        rows.append(dict(p=p, f=f, variant=var, informative_affected_cells=int(len(aff) // 4), det_synthesis_mean=float(per.mean()), det_synthesis_min_seed=float(per.min()),
                         det_E3_absent=float((aff.e3_absent >= 0.15).mean()), det_E2_supportive=float(e2c), reliable=bool(per.mean() >= 0.70)))
    DT = pd.DataFrame(rows)
    old = pd.read_csv(P.OUT.parent / "lineC_pos/detection_by_scenario.csv")
    DT = DT.merge(old[["p", "f", "variant", "det_E1_reduced"]], on=["p", "f", "variant"], how="left")
    DT.to_csv(OUT / "detection_by_scenario_newrule.csv", index=False, float_format="%.3f")
    res["detection"] = DT.round(3).to_dict("records")
    res["reliable_counts"] = {int(k): int(v) for k, v in DT.groupby("variant").reliable.sum().items()}
    rr = []
    for _, cell in BT[BT.verdict == "반박"].iterrows():
        sub = CR[(CR.direction == cell.direction) & (CR.band == cell.band) & (CR.seg == cell.seg) & CR.affected]
        row = dict(direction=cell.direction, band=cell.band, seg=cell.seg, scenarios=int(len(sub)))
        for f in FS_:
            s_ = sub[sub.f == f]
            row[f"nonrefute_f{f}"] = float((s_.verdict != "반박").mean()) if len(s_) else np.nan
            row[f"support_f{f}"] = float((s_.verdict == "지원").mean()) if len(s_) else np.nan
        for nm in ("nonrefute", "support"):
            ok = [f for f in FS_ if row[f"{nm}_f{f}"] >= 0.70]
            row[f"min_f_{nm}"] = min(ok) if ok else ("검증 못 함" if len(sub) == 0 else ">0.5")
        rr.append(row)
    RR = pd.DataFrame(rr)
    RR.to_csv(OUT / "refutation_range.csv", index=False, float_format="%.3f")
    res["refutation_cells"] = int(len(RR))
    res["refutation_min_f_support_counts"] = RR.min_f_support.astype(str).value_counts().to_dict()
    res["refutation_min_f_nonrefute_counts"] = RR.min_f_nonrefute.astype(str).value_counts().to_dict()
    ev = pd.read_csv(P.OUT.parent / "lineC_pool3/candidate_arrival_events_pool3.csv")
    dirn = {d: i for i, d in enumerate(dn)}
    ev["_di"] = ev.direction.map(dirn)
    ev["_i"] = ev.train_id.str[-4:].astype(int) - 1
    pos = np.array([c["order"][di].index(s) for di, s in zip(ev._di, ev.stationID)])
    ev["_g"] = [[g for g, (a, z) in enumerate(SEG) if a <= k < z][0] for k in pos]
    ev["_b"] = [c["bidx"][di][i] for di, i in zip(ev._di, ev._i)]
    ev["low_signal"] = [(b < 0) or (not zone[di, b]) for di, b in zip(ev._di, ev._b)]
    vmap = {(r_.direction, r_.band, r_.seg): r_.verdict for r_ in BT.itertuples()}
    share = BT.assign(r=BT.verdict.eq("반박")).groupby(["direction", "band"]).r.mean().to_dict()
    ev["structure_status"] = [("미확인" if ls else vmap[(dn[di], BANDS[b][0], g)]) for ls, di, b, g in zip(ev.low_signal, ev._di, ev._b, ev._g)]
    ev["refuted_share_cell"] = [(np.nan if ls else share[(dn[di], BANDS[b][0])]) for ls, di, b in zip(ev.low_signal, ev._di, ev._b)]
    fin = ev.rename(columns={"arrival_time_of_day": "arrival_time"})[["train_id", "direction", "stationID", "arrival_time", "imputed", "impute_evidence", "observed_peak_within_45s",
                                                                      "lag_out_s", "lag_in_s", "tail_unsupported_flag", "group", "low_signal", "structure_status", "refuted_share_cell"]]
    fin.to_csv(FIN / "candidate_arrival_events_final.csv", index=False)
    res["final_file"] = dict(rows=len(fin), trains=int(fin.train_id.nunique()), imputed_trains=int(fin[fin.imputed].train_id.nunique()), low_signal_trains=int(fin[fin.low_signal].train_id.nunique()),
                             structure_status_rows=fin.structure_status.value_counts().to_dict())
    (OUT / "pos2_metrics.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "detection"}, indent=1, default=float, ensure_ascii=False))
    print(DT.round(2).to_string())


if __name__ == "__main__":
    main()
