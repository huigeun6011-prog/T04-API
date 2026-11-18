"""새 날짜 확인 시험: 같은 역·방향의 7~22시 시간대 순서. 기준: criteria.md '새 날짜 확인 시험'. 결과: outputs/hangzhou/od_test/confirm_hours.json"""
import os
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_v] = "1"
import json
import sys
from multiprocessing import Pool
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import c_truth as T
import run_route_rank as RR

DATES = ["2019-01-03", "2019-01-11", "2019-01-21", "2019-01-24"]
EST = ["od_uniform", "adam1000"]


def solve(arg):
    T.low_priority()
    RR.get_loads(*arg)
    return arg


def sp(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5 or a.std() == 0 or b.std() == 0:
        return np.nan
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def evaluate(date, tt):
    ev, n, NH = tt.ev, tt.NS, T.NH
    tinfo = ev.drop_duplicates("train_idx")
    elig = ~tinfo.imputed_train.to_numpy() & ~tinfo.low_signal_train.to_numpy()
    m = np.repeat(elig, n) & (ev.is_destination.to_numpy() == 0)
    a = T.assign(T.read_pax(date, tt), tt)
    _, B, A = T.truth_from_assignment(a, tt)
    Bm, Am = B.reshape(n, NH), A.reshape(n, NH)
    zo = np.load(T.CACHE / f"od_test_loads_{date}_od_uniform.npz"); za = np.load(T.CACHE / f"od_test_loads_{date}_adam1000.npz")
    df = pd.DataFrame({"s": ev.station_idx.to_numpy(), "h": ev.hour.to_numpy(), "dir": ev.dir_code.to_numpy(), "t": zo["true"].ravel(),
                       "od": zo["est"].ravel(), "ad": za["est"].ravel()})[m]
    g = df.groupby(["s", "dir", "h"])[["t", "od", "ad"]].mean().reset_index()
    g = g[(g.h >= 7) & (g.h <= 22)].copy()
    g["N1"] = g.h.map(lambda h: Bm[:, h - 5].sum())
    g["N2"] = [Bm[s, h - 5] + Am[s, h - 5] for s, h in zip(g.s, g.h)]
    g["N4"] = g.h.map(g.groupby("h").t.mean())
    rows = []
    for (s, dr), x in g.groupby(["s", "dir"]):
        if len(x) < 14 or x.t.max() < 20:
            continue
        tr = x.t.rank(method="first").to_numpy()
        row = dict(date=date, s=int(s), dir=int(dr), n=len(x))
        for k in ("od", "ad", "N1", "N2", "N4"):
            er = x[k].rank(method="first").to_numpy(); diff = np.abs(tr - er)
            row[f"{k}_sp"] = sp(x.t, x[k]); row[f"{k}_mad"] = float(diff.mean())
            for c in (0, 1, 2):
                row[f"{k}_le{c}"] = float((diff <= c).mean())
            row[f"{k}_top1"] = float(x.h.iloc[int(np.argmin(x[k].to_numpy()))] == x.h.iloc[int(np.argmin(x.t.to_numpy()))])
            row[f"{k}_top3"] = float(x.h.iloc[int(np.argmin(x[k].to_numpy()))] in x.sort_values("t").h.iloc[:3].tolist())
        rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    with Pool(3) as pool:
        for r in pool.imap_unordered(solve, [(d, e) for d in DATES for e in EST]):
            print("solved", r, flush=True)
    tt = T.Timetable()
    p = pd.concat([evaluate(d, tt) for d in DATES], ignore_index=True)
    p.to_csv(T.OUT / "confirm_hours_rows.csv", index=False, encoding="utf-8-sig", float_format="%.4f")
    keys = ["od", "ad", "N1", "N2", "N4"]
    summ = {k: {m: float(p[f"{k}_{m}"].mean()) for m in ("sp", "mad", "le0", "le1", "le2", "top1", "top3")} for k in keys}
    by_day = {d: {k: float(x[f"{k}_le2"].mean()) for k in keys} | {"od_sp": float(x.od_sp.mean())} for d, x in p.groupby("date")}
    best_naive = max(summ[k]["sp"] for k in ("N1", "N2", "N4"))
    verdict = (summ["od"]["le2"] - summ["ad"]["le2"] >= 0.10) and (summ["od"]["sp"] - best_naive >= 0.10)
    wins = dict(od_closer=float((p.od_mad < p.ad_mad).mean()), tie=float((p.od_mad == p.ad_mad).mean()), adam_closer=float((p.od_mad > p.ad_mad).mean()))
    out = dict(n_orderings=int(len(p)), summary=summ, by_day_le2=by_day, pairwise=wins, best_naive_spearman=best_naive,
               verdict="유지됨" if verdict else "유지되지 않음")
    (T.OUT / "confirm_hours.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
