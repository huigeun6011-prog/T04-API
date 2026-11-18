"""경로 단위(출발역→도착역, 시간 창) 열차 순위 시험. 기준: criteria.md '추가 기준: 경로 단위 순위'.
  python run_route_rank.py [--workers 3]      결과: outputs/hangzhou/od_test/route_rank/"""
import os
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_v] = "1"
import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c_adam as Ad
import c_od as O
import c_truth as T
import run_od_test as R

OUT = T.OUT / "route_rank"
WINDOWS = {"am_commute_7_9": (7, 8), "midday_12_14": (12, 13), "pm_commute_17_19": (17, 18), "night_20_22": (20, 21)}
HOURS_RANK = list(range(7, 23))
EST = ["od_uniform", "od_real", "adam1000"]


def loads_matrix(frame, K, n):
    return frame.load.to_numpy().reshape(K, n)


def get_loads(date, est):
    """(true_load[K,n], est_load[K,n]) 모두 이동 방향 위치(pos) 순서."""
    cp = T.CACHE / f"od_test_loads_{date}_{est}.npz"
    tt = T.Timetable()
    if cp.exists():
        z = np.load(cp)
        return tt, z["true"], z["est"]
    P = O.build_problem(tt, T.NH)
    a = T.assign(T.read_pax(date, tt), tt)
    x_true, B, A = T.truth_from_assignment(a, tt)
    true_frame = O.to_frame(P, x_true)
    if est == "adam1000":
        est_frame, _ = Ad.solve(tt, B, A, T.NH, epochs=1000)
    else:
        spec = R.QS["uniform" if est == "od_uniform" else "real"]
        g = O.hop_g(P, spec["kind"], truth_x=x_true)
        x, info = O.fit(P, B, A, O.base_q(P, B, g), 0.01)
        est_frame = O.to_frame(P, x)
    tl, el = loads_matrix(true_frame, tt.K, tt.NS), loads_matrix(est_frame, tt.K, tt.NS)
    np.savez_compressed(cp, true=tl, est=el)
    return tt, tl, el


def seg_mean(L, rows, po, pd_):
    cs = np.concatenate([np.zeros((L.shape[0], 1)), np.cumsum(L, axis=1)], axis=1)
    return (cs[rows, pd_] - cs[rows, po]) / (pd_ - po)


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or a.std() == 0 or b.std() == 0:
        return np.nan
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def run_queries(tt, TL, EL):
    ev = tt.ev
    n = tt.NS
    elig = ~tt.ev.drop_duplicates("train_idx").set_index("train_idx").loc[np.arange(tt.K), ["imputed_train"]].imputed_train.to_numpy() \
        & ~tt.ev.drop_duplicates("train_idx").set_index("train_idx").loc[np.arange(tt.K), ["low_signal_train"]].low_signal_train.to_numpy()
    hour_at = ev.hour.to_numpy().reshape(tt.K, n)               # pos 순서
    # 시간 평균 오라클 점수용: 정답의 (역, 시간, 방향) 셀 평균 재차를 모든 열차 정차에 부여(평가 열차만으로 계산)
    sidx = ev.station_idx.to_numpy().reshape(tt.K, n)
    dirc = tt.dircode
    cellmean = np.zeros_like(TL)
    df = pd.DataFrame({"k": np.repeat(np.arange(tt.K), n), "s": sidx.ravel(), "h": hour_at.ravel(), "d": np.repeat(dirc, n), "t": TL.ravel(),
                       "ok": np.repeat(elig, n) & (ev.is_destination.to_numpy() == 0)})
    gm = df[df.ok].groupby(["s", "h", "d"]).t.mean()
    cellmean = df.join(gm.rename("cm"), on=["s", "h", "d"]).cm.fillna(0).to_numpy().reshape(tt.K, n)
    rows = []
    hourrank = {}
    for dc in (0, 1):
        trains = np.flatnonzero((dirc == dc) & elig)
        for o in range(n):
            for d in range(n):
                if (d - o) * (1 if dc == 1 else -1) < 4:
                    continue
                po = o if dc == 1 else n - 1 - o
                pdd = d if dc == 1 else n - 1 - d
                if pdd - po < 4:
                    continue
                h_o = hour_at[trains, po]
                t_s, e_s, c_s = seg_mean(TL, trains, po, pdd), seg_mean(EL, trains, po, pdd), seg_mean(cellmean, trains, po, pdd)
                for wname, hrs in WINDOWS.items():
                    m = np.isin(h_o, hrs)
                    if m.sum() < 6:
                        continue
                    t, e, c = t_s[m], e_s[m], c_s[m]
                    third = np.sort(t)[2]
                    best_t, mean_t = t.min(), t.mean()
                    ch = e <= e.min() + 1e-9
                    chc = c <= c.min() + 1e-9
                    den = mean_t - best_t
                    nreg = (lambda sel: float((np.mean(t[sel]) - best_t) / den)) if den > 1e-9 else (lambda sel: np.nan)
                    rows.append(dict(o=o, d=d, dir=dc, window=wname, n=int(m.sum()),
                                     sp_est=spearman(t, e), sp_cell=spearman(t, c),
                                     hit_est=float(np.mean(t[ch] <= third)), hit_cell=float(np.mean(t[chc] <= third)), hit_rand=3 / m.sum(),
                                     nreg_est=nreg(ch), nreg_cell=nreg(chc)))
                # 시간별 순위: 각 시간에 대해 (정답 최선 점수) vs (추정이 고른 열차의 추정 점수)로 순위를 비교
                est_scores, true_best = [], []
                for h in HOURS_RANK:
                    mm = h_o == h
                    if mm.any():
                        true_best.append(t_s[mm].min()); est_scores.append(e_s[mm].min())
                if len(true_best) >= 8:
                    hourrank[(dc, o, d)] = spearman(true_best, est_scores)
    return pd.DataFrame(rows), hourrank


def task(arg):
    date, est = arg
    path = OUT / f"{date}__{est}.json"
    if path.exists():
        return str(path)
    T.low_priority()
    t0 = time.time()
    tt, TL, EL = get_loads(date, est)
    q, hr = run_queries(tt, TL, EL)
    res = dict(date=date, est=est, n_queries=int(len(q)), seconds=time.time() - t0,
               hour_rank_spearman_mean=float(np.nanmean(list(hr.values()))), hour_rank_pairs=len(hr),
               by_window={w: {k: float(np.nanmean(g[k])) for k in ("sp_est", "sp_cell", "hit_est", "hit_cell", "hit_rand", "nreg_est", "nreg_cell")} | {"n": int(len(g))}
                          for w, g in q.groupby("window")},
               overall={k: float(np.nanmean(q[k])) for k in ("sp_est", "sp_cell", "hit_est", "hit_cell", "hit_rand", "nreg_est", "nreg_cell")})
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only")
    a = ap.parse_args()
    tasks = [(d, e) for d in R.DATES for e in EST]
    if a.only:
        d, e = a.only.split(":")
        tasks = [(d, e)]
    with Pool(min(a.workers, 3)) as pool:
        for r in pool.imap_unordered(task, tasks):
            print("done", Path(r).name, flush=True)
