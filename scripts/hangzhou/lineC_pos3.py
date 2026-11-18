"""lineC_pos3: positive control for the cells lineC_pos2 could not test (midday/evening bands, front turn positions). Rules: outputs/hangzhou/lineC_pos3/criteria.md."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import lineC_pool as P
from lineC_pos2 import BANDS, SEG, Ncounts, e23, setup, verdicts2

OUT = P.OUT.parent / "lineC_pos3"
P2OUT = P.OUT.parent / "lineC_pos2"
FS_, SEEDS_ = (0.10, 0.25, 0.50), (1, 2, 3, 4)
GROUPS = {"rush": ((1, 3), (3, 8)), "midday": ((2,), (3, 8, 13, 18, 23)), "evening": ((4,), (3, 8, 13, 18, 23))}
GID = {"rush": 1, "midday": 2, "evening": 3}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    c = setup()
    ps, tr, tabs, Lo, dn = c["ps"], c["tr"], c["tabs"], c["Lo"], c["dnames"]
    ntr = c["ntr"]
    Z = pd.read_csv(P2OUT / "analysis_zone.csv")
    zone = np.zeros((2, 5), bool)
    for _, r in Z.iterrows():
        zone[dn.index(r.direction), [b[0] for b in BANDS].index(r.band)] = bool(r.in_zone)
    BT = pd.read_csv(P2OUT / "baseline_verdict_60cells.csv")
    rows = []
    scen = [("none", 0, 0.0, 0, s) for s in SEEDS_]
    for g, (bands, ps_) in GROUPS.items():
        scen += [(g, p, f, v, s) for p in ps_ for f in FS_ for v in (0, 1) for s in SEEDS_]
    for (g, p, f, var, seed) in scen:
        bands = GROUPS[g][0] if g != "none" else ()
        r = np.random.default_rng(20190108 + 1000 * seed + 10 * p + int(100 * f) + var + 100000 * GID.get(g, 0))
        sel = {di: np.zeros(ntr[di], bool) for di in (0, 1)}
        for di in (0, 1):
            for b in bands:
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
                posx2[mv & (ps.d == di)] = p
            keep = keep | mv
        e2, e2n, pr, ab, typ = e23(Ncounts(c, keep, posx2), c["bidx"], r)
        V = verdicts2(e2, e2n, pr, ab, typ, zone)
        for di in (0, 1):
            for b in range(5):
                for sg in range(6):
                    rows.append(dict(group=g, p=p, f=f, variant=var, seed=seed, direction=dn[di], band=BANDS[b][0], seg=sg,
                                     affected=bool(f > 0 and b in bands and SEG[sg][0] > p), e2_share=e2[di, b, sg], e2_null=e2n[di, b, sg],
                                     e3_present=pr[di, b, sg], e3_absent=ab[di, b, sg], typ=typ[di, b, sg], verdict=V[di, b, sg]))
        print("scenario", g, p, f, var, seed, flush=True)
    CR = pd.DataFrame(rows)
    CR.to_csv(OUT / "pos3_cells.csv", index=False, float_format="%.3f")
    key = BT[["direction", "band", "seg", "typ", "in_zone", "verdict"]].rename(columns={"typ": "base_typ", "verdict": "base_verdict"})
    CR = CR.merge(key, on=["direction", "band", "seg"])
    ctrl = CR[(CR.group == "none") & CR.in_zone]
    res = dict(false_support=dict(seeds=4, cell_runs=int(len(ctrl)), support_runs=int((ctrl.verdict == "지원").sum())))
    det = []
    for (g, p, f, var), x in CR[CR.group != "none"].groupby(["group", "p", "f", "variant"]):
        aff = x[x.affected & (x.base_typ >= 100) & x.in_zone]
        if len(aff) == 0:
            det.append(dict(group=g, p=p, f=f, variant=var, informative_affected_cells=0, det_synthesis_mean=np.nan, det_synthesis_min_seed=np.nan, reliable=None)); continue
        per = aff.groupby("seed").verdict.apply(lambda s: (s == "지원").mean())
        det.append(dict(group=g, p=p, f=f, variant=var, informative_affected_cells=int(len(aff) // 4), det_synthesis_mean=float(per.mean()), det_synthesis_min_seed=float(per.min()),
                        det_E3_absent=float((aff.e3_absent >= 0.15).mean()), reliable=bool(per.mean() >= 0.70)))
    DT = pd.DataFrame(det)
    DT.to_csv(OUT / "detection_by_scenario_pos3.csv", index=False, float_format="%.3f")
    res["detection"] = DT.round(3).to_dict("records")
    # merged refutation range with pos2 scenarios (rush bands, p 13/18/23)
    old = pd.read_csv(P2OUT / "pos2_cells.csv")
    old = old.merge(key, on=["direction", "band", "seg"])
    allc = pd.concat([old[["f", "variant", "seed", "direction", "band", "seg", "affected", "verdict"]].assign(src="pos2"),
                      CR[CR.group != "none"][["f", "variant", "seed", "direction", "band", "seg", "affected", "verdict"]].assign(src="pos3")])
    rr = []
    for _, cell in BT[BT.verdict == "반박"].iterrows():
        sub = allc[(allc.direction == cell.direction) & (allc.band == cell.band) & (allc.seg == cell.seg) & allc.affected]
        row = dict(direction=cell.direction, band=cell.band, seg=cell.seg, scenarios=int(len(sub)))
        for f in FS_:
            s_ = sub[sub.f == f]
            row[f"nonrefute_f{f}"] = float((s_.verdict != "반박").mean()) if len(s_) else np.nan
            row[f"support_f{f}"] = float((s_.verdict == "지원").mean()) if len(s_) else np.nan
        for nm in ("nonrefute", "support"):
            ok = [f for f in FS_ if row[f"{nm}_f{f}"] >= 0.70]
            row[f"min_f_{nm}"] = min(ok) if ok else ("검증 못 함" if len(sub) == 0 else "반박이지만 검출력 낮음")
        rr.append(row)
    RR = pd.DataFrame(rr)
    RR.to_csv(OUT / "refutation_range_updated.csv", index=False, float_format="%.3f")
    res["refuted_cells"] = int(len(RR))
    res["tested_cells"] = int((RR.scenarios > 0).sum())
    res["min_f_support_counts"] = RR.min_f_support.astype(str).value_counts().to_dict()
    res["min_f_nonrefute_counts"] = RR.min_f_nonrefute.astype(str).value_counts().to_dict()
    res["untested"] = RR[RR.scenarios == 0][["direction", "band", "seg"]].to_dict("records")
    res["low_power"] = RR[(RR.scenarios > 0) & (RR.min_f_nonrefute == "반박이지만 검출력 낮음")][["direction", "band", "seg"]].to_dict("records")
    (OUT / "pos3_metrics.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "detection"}, indent=1, default=float, ensure_ascii=False))
    print(DT.round(2).to_string())


if __name__ == "__main__":
    main()
