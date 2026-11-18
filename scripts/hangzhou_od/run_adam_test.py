"""Adam 비교 실행기(OD와 같은 입력·정답·평가). 기준: criteria.md '추가 기준'.
  python run_adam_test.py [--workers 3]          결과: outputs/hangzhou/od_test/runs_adam/"""
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

RUNS_A = T.OUT / "runs_adam"
CFGS = [("adam1000", 1000, 0.0), ("adam1000", 1000, 0.02), ("adam1000", 1000, 0.05), ("adam200", 200, 0.0)]


def task(arg):
    date, (name, epochs, noise) = arg
    path = RUNS_A / f"{date}__{name}__n{noise}.json"
    if path.exists():
        return str(path)
    T.low_priority()
    t_all = time.time()
    tt = T.Timetable()
    P = O.build_problem(tt, T.NH)
    a = T.assign(T.read_pax(date, tt), tt)
    x_true, B, A = T.truth_from_assignment(a, tt)
    true_frame = O.to_frame(P, x_true)
    Bn, An = B.copy(), A.copy()
    if noise:
        rng = np.random.default_rng(R.NOISE_SEED)
        Bn = Bn * np.clip(1 + noise * rng.standard_normal(len(Bn)), .5, None)
        An = An * np.clip(1 + noise * rng.standard_normal(len(An)), .5, None)
    t0 = time.time()
    est_frame, info = Ad.solve(tt, Bn, An, T.NH, epochs=epochs)
    fit_s = time.time() - t0
    assert (est_frame.train_id.to_numpy() == P["ev"].train_id.to_numpy()).all()
    ev_res, n_eval = R.evaluate(P, true_frame, est_frame)
    ms = O.marginal_stats(P, est_frame, Bn, An)
    res = dict(date=date, config=f"{name}__n{noise}", name=name, epochs=epochs, noise=noise, n_eval_events=n_eval,
               true_total=float(x_true.sum()), fit=dict(seconds=fit_s, **info), marginal=ms, eval=ev_res, seconds_total=time.time() - t_all,
               terminal_load_abs_max=float(est_frame.loc[est_frame.is_destination == 1, "raw_load"].abs().max()),
               neg_load_share=float((est_frame.raw_load < -1e-9).mean()))
    RUNS_A.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)


def summarize():
    rows = []
    for p in sorted(RUNS_A.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        for sub in ("all", "commute", "midday_9_17", "evening_19_24", "toward_66", "toward_34"):
            m = r["eval"][sub]
            rows.append(dict(date=r["date"], est=r["name"], noise=r["noise"], subset=sub, recovered=m["recovered"],
                             cell_spearman=m["cell"]["spearman"], cell_sum_ratio=m["cell"]["sum_ratio"], cell_top10_ratio=m["cell"]["top10pct_ratio"],
                             train_spearman=m["train"]["spearman"], train_dev_corr=m["train"]["dev_corr"], train_shuffle_dev=m["train"]["shuffle_dev_corr"],
                             train_top1_ratio=m["train"]["top1pct_ratio"], seg_rel_mae_med=m["train"]["seg_rel_mae_median"],
                             fit_s=round(r["fit"]["seconds"], 1), best_epoch=r["fit"]["best_epoch"],
                             terminal_abs_max=r["terminal_load_abs_max"], neg_share=r["neg_load_share"]))
    df = pd.DataFrame(rows)
    df.to_csv(T.OUT / "summary_adam.csv", index=False, encoding="utf-8-sig")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only")
    a = ap.parse_args()
    tasks = [(d, c) for d in R.DATES for c in CFGS]
    if a.only:
        d, n = a.only.split(":")
        nm, noise = n.split("__")
        tasks = [(d, next(c for c in CFGS if c[0] == nm and c[2] == float(noise[1:])))]
    with Pool(min(a.workers, 3)) as pool:
        for r in pool.imap_unordered(task, tasks):
            print("done", Path(r).name, flush=True)
    summarize()
