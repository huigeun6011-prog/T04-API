"""lineC_weekend: pool2 + pool3 rules and constants unchanged, applied to the weekend group (1/05,06,12,13,19,20 + 1/01). Rules: outputs/hangzhou/lineC_final/criteria_weekend.md."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lineC_pool as P
import lineC_pool2 as P2
import lineC_pool3 as P3
import lineC_struct as S
import lineC_stack as ST
from lineC_route_gate import build_topology, corridor_order, read_tags
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d

FIN = P.OUT.parent / "lineC_final"
DAYS = ["2019-01-05", "2019-01-06", "2019-01-12", "2019-01-13", "2019-01-19", "2019-01-20", "2019-01-01"]
BANDS, EDGES, BLEN, DAY = S.BANDS, S.EDGES, S.BLEN, S.DAY
HOLD = "2019-01-12"


def e1_expected(DF, days, active, tabs2, dnames, order):
    n, nd = len(active), len(days)
    rng = np.random.default_rng(20190108)
    C = np.zeros((nd, 2, n, 5)); Cn = np.zeros((S.NULL_REPS, nd, 2, n, 5)); X = np.zeros((nd, 2, n, 5))
    for i, d in enumerate(days):
        for di in (0, 1):
            sub = DF[d][DF[d].direction == dnames[di]]
            for s, g in sub.groupby("exit_station"):
                k = order[di].index(s)
                t = g.exit_seconds.to_numpy()
                h = np.bincount(t, minlength=DAY)
                X[i, di, k] = np.histogram(t, bins=EDGES)[0]
                C[i, di, k] = S.bandcount(S.peak_arr(h))
                lam = gaussian_filter1d(h.astype(float), 300)
                for r in range(S.NULL_REPS):
                    Cn[r, i, di, k] = S.bandcount(S.peak_arr(rng.poisson(np.clip(lam, 0, None))))
        print("e1 day", d, flush=True)
    L = np.array(BLEN) * nd
    rate = C.sum(0) / L
    nrate = Cn.sum(1).mean(0) / L
    Xs = X.sum(0) / nd
    H, cells = {}, []
    for di in (0, 1):
        ntrain = [int(((tabs2[dnames[di]]["arr"][:, 0] >= BANDS[b][1] * 3600) & (tabs2[dnames[di]]["arr"][:, 0] < BANDS[b][2] * 3600)).sum()) for b in range(5)]
        for b in range(5):
            ntr = Xs[di, :, b] / max(ntrain[b], 1)
            exc = np.where(rate[di, :, b] > 0, (rate[di, :, b] - nrate[di, :, b]) / rate[di, :, b], -1)
            inf = (ntr >= S.NTR_MIN) & (exc >= S.EXCESS_MIN)
            hw = np.where(rate[di, :, b] > 0, 3600 / np.where(rate[di, :, b] > 0, rate[di, :, b], 1), np.nan)
            sel = [k for k in range(4, 28) if inf[k] and np.isfinite(hw[k])]
            for k in range(n):
                cells.append(dict(direction=dnames[di], band=BANDS[b][0], pos=k, headway_s=hw[k], exits_per_train=ntr[k], excess=exc[k], informative=bool(inf[k])))
            if len(sel) >= 3:
                H[(dnames[di], BANDS[b][0])] = float(np.median(hw[sel]))
    return H, pd.DataFrame(cells)


def main():
    FIN.mkdir(parents=True, exist_ok=True)
    gate, trips, _ = read_tags()
    tracks, membership, _, _, _ = build_topology(gate)
    corridor = corridor_order(tracks["C"])
    active = [s for s in corridor if gate.get(s) == "C"]
    first, last = active[0], active[-1]
    DF = {d: P.load_day(d, first, last) for d in DAYS}
    dnames = [f"toward_{first}", f"toward_{last}"]
    order = {0: active[::-1], 1: active}
    ST.find_refs = P2.find_refs2
    for d in DAYS:
        P2.DAYREFS[d] = P2.day_refs_cache(d, DF[d], active)
    res = {"days": DAYS}
    # pool2 (weekend)
    _, _, tabs2, info2, ps2, Lo2, Li2, _, r2 = P2.variant(DAYS, DF, active, True, "pool2_weekend")
    r2["assignable_by_hour"], _ = P2.pax_hour_assignable(tabs2, ps2, active, Lo2, Li2)
    res["pool2_weekend"] = r2
    del ps2
    # E1 expected from weekend input
    H, E1 = e1_expected(DF, DAYS, active, tabs2, dnames, order)
    E1.to_csv(FIN / "weekend_e1_headway_by_station.csv", index=False, float_format="%.3f")
    res["E1_expected_headway_s"] = {f"{k[0]}|{k[1]}": v for k, v in H.items()}
    P3.H = H
    # pool3 (weekend)
    anchors, dirs, tabs, info, fr, logs = P3.build_pool3(DAYS, DF, active, H)
    dayidx = np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(DAYS)])
    ps = P.PaxSet(anchors, active, dayidx)
    Lo, Li, lt = P.fit_lags(tabs, ps, active)
    r3 = dict(trains=fr["trains"], both_ends=fr["both_ends_within_2"], small=fr["small_1_2_observed"], gaps=P2.gap_metrics(tabs),
              imputed={k: int(v["imputed"].sum()) for k, v in info.items()}, relaxed_added={k: int((v["evidence"] == "relaxed_stack").sum()) for k, v in info.items()},
              fill_log=logs, lag30_0=P.eval_group(tabs, ps, active, *P.const_lags(tabs), days=DAYS), fitted=P.eval_group(tabs, ps, active, Lo, Li, days=DAYS))
    r3["assignable_by_hour"], _ = P2.pax_hour_assignable(tabs, ps, active, Lo, Li)
    res["pool3_weekend"] = r3
    sym = {}
    for lab, g in (("pool2", r2["gaps"]), ("pool3", r3["gaps"])):
        sym[lab] = {b: float(g[dnames[0]]["mean_headway_s"][b] / g[dnames[1]]["mean_headway_s"][b]) for b in g[dnames[0]]["mean_headway_s"]}
    res["headway_ratio_toward34_over_toward66"] = sym
    # holdout day
    rest = [d for d in DAYS if d != HOLD]
    anc_r, _, tabs_r, info_r, fr_r, logs_r = P3.build_pool3(rest, DF, active, H)
    ps_r = P.PaxSet(anc_r, active, np.concatenate([np.full(len(DF[d]), i) for i, d in enumerate(rest)]))
    Lo_r, Li_r, _ = P.fit_lags(tabs_r, ps_r, active)
    res["holdout_day"] = dict(day=HOLD, trains=fr_r["trains"], relaxed_added={k: int((v["evidence"] == "relaxed_stack").sum()) for k, v in info_r.items()},
                              without_day_fitted=P.eval_group(tabs_r, P.PaxSet(DF[HOLD], active), active, Lo_r, Li_r)["all"], with_day_fitted=r3["fitted"][HOLD],
                              pool2_with_day=r2["fitted"][HOLD], gaps=P2.gap_metrics(tabs_r))
    # final file (same columns as weekday file)
    ev = []
    for name, t in tabs.items():
        inf = info[name]
        for i in range(len(t["arr"])):
            tid = f"C-weekend3-{name}-P{i + 1:04d}"
            for k, s in enumerate(t["stations"]):
                sec = t["arr"][i, k]
                ev.append((tid, name, int(s), f"{int(sec) // 3600:02d}:{int(sec) % 3600 // 60:02d}:{int(sec) % 60:02d}", bool(inf["imputed"][i]), inf["evidence"][i],
                           bool(inf["obs"][i, k]), round(float(Lo[name][k]), 1), round(float(Li[name][k]), 1), bool(inf["tail"][i]), "weekend", "미확인", "미확인", np.nan))
    cols = ["train_id", "direction", "stationID", "arrival_time", "imputed", "impute_evidence", "observed_peak_within_45s", "lag_out_s", "lag_in_s", "tail_unsupported_flag", "group",
            "low_signal", "structure_status", "refuted_share_cell"]
    pd.DataFrame(ev, columns=cols).to_csv(FIN / "candidate_arrival_events_final_weekend.csv", index=False)
    lt.to_csv(FIN / "lags_by_station_weekend.csv", index=False, float_format="%.2f")
    pd.DataFrame(logs).to_csv(FIN / "weekend_fill_log.csv", index=False, float_format="%.2f")
    (FIN / "weekend_metrics.json").write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("E1_expected_headway_s", "headway_ratio_toward34_over_toward66", "holdout_day")}, indent=1, default=float, ensure_ascii=False)[:5000])


if __name__ == "__main__":
    main()
