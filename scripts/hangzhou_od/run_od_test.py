"""항저우 C선 OD 역산 시험 실행기. 기준: outputs/hangzhou/od_test/criteria.md (실행 전 고정).
  python run_od_test.py --stage all --workers 3      # 전체
  python run_od_test.py --only 2019-01-09:uniform__lam0.01__n0   # 한 건 시험
결과: outputs/hangzhou/od_test/runs/<날짜>__<설정>.json"""
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
import c_od as O
import c_truth as T

DATES = ["2019-01-09", "2019-01-17", "2019-01-23"]
QS = {"uniform": dict(kind="uniform"), "real": dict(kind="real"),
      "grav0.05": dict(kind="gravity", beta=0.05), "grav0.1": dict(kind="gravity", beta=0.1),
      "grav0.2": dict(kind="gravity", beta=0.2), "grav0.4": dict(kind="gravity", beta=0.4),
      "real_short": dict(kind="real", tilt=-0.2), "real_long": dict(kind="real", tilt=0.2)}
NOISE_SEED, SHUFFLE_SEED = 7, 20190108
RUNS = T.OUT / "runs"


def cfg_name(q, lam, noise):
    return f"{q}__lam{lam}__n{noise}"


def all_configs(stage):
    cfgs = []
    if stage in ("1", "all"):
        cfgs += [(q, 0.01, 0.0) for q in QS]
    if stage in ("2", "all"):
        cfgs += [(q, 0.1, 0.0) for q in ("uniform", "real")]
        cfgs += [(q, 0.01, s) for q in ("uniform", "real") for s in (0.02, 0.05)]
    return cfgs


def corr(a, b, how):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or a.std() == 0 or b.std() == 0:
        return None
    r = pd.Series(a).rank().corr(pd.Series(b).rank()) if how == "s" else float(np.corrcoef(a, b)[0, 1])
    return None if pd.isna(r) else float(r)


def metrics(ev, true, est, rng):
    """ev: 평가 이벤트 DataFrame(station_idx, hour_idx, dir_code, ...), true/est: 같은 길이 배열."""
    e = ev[["station_idx", "hour_idx", "dir_code"]].copy()
    e["t"], e["e"] = np.asarray(true, float), np.asarray(est, float)
    key = ["station_idx", "hour_idx", "dir_code"]
    g = e.groupby(key)[["t", "e"]].mean()
    top = g.t >= g.t.quantile(0.9)
    e["tr"] = e.t - e.groupby(key).t.transform("mean")
    e["er"] = e.e - e.groupby(key).e.transform("mean")
    top1 = e.t >= e.t.quantile(0.99)
    sh = e.copy()
    sh["e"] = sh.groupby(key).e.transform(lambda s: rng.permutation(s.to_numpy()))
    sh["er"] = sh.e - sh.groupby(key).e.transform("mean")
    seg = e.groupby("station_idx")[["t", "e"]].sum()
    cell = dict(n=int(len(g)), spearman=corr(g.t, g.e, "s"), pearson=corr(g.t, g.e, "p"), sum_ratio=float(g.e.sum() / g.t.sum()),
                top10pct_ratio=float(g.e[top].sum() / g.t[top].sum()), mae_rel=float((g.e - g.t).abs().sum() / g.t.sum()))
    train = dict(n=int(len(e)), spearman=corr(e.t, e.e, "s"), sum_ratio=float(e.e.sum() / e.t.sum()),
                 dev_corr=corr(e.tr, e.er, "p"), top1pct_ratio=float(e.e[top1].mean() / e.t[top1].mean()),
                 shuffle_spearman=corr(sh.t, sh.e, "s"), shuffle_dev_corr=corr(sh.tr, sh.er, "p"),
                 seg_rel_mae_median=float(((seg.e - seg.t).abs() / seg.t.clip(lower=1)).median()))
    ok = (cell["spearman"] is not None and cell["spearman"] >= 0.9 and 0.9 <= cell["sum_ratio"] <= 1.1 and 0.8 <= cell["top10pct_ratio"] <= 1.2)
    return dict(cell=cell, train=train, recovered=bool(ok))


def subsets(ev):
    h, d = ev.hour.to_numpy(), ev.dir_code.to_numpy()
    out = {"all": np.ones(len(ev), bool), "early_5_7": h < 7, "commute": ((h >= 7) & (h < 9)) | ((h >= 17) & (h < 19)),
           "midday_9_17": (h >= 9) & (h < 17), "evening_19_24": h >= 19, "toward_66": d == 1, "toward_34": d == 0}
    return out


def evaluate(P, true_frame, est_frame, label_rng_seed=SHUFFLE_SEED):
    ev = P["ev"]
    m = ((ev.is_destination == 0) & ~ev.imputed_train & ~ev.low_signal_train).to_numpy()
    e = ev[m].reset_index(drop=True)
    tl, el = true_frame.load.to_numpy()[m], est_frame.load.to_numpy()[m]
    res = {}
    for name, sub in subsets(e).items():
        rng = np.random.default_rng(label_rng_seed)
        res[name] = metrics(e[sub], tl[sub], el[sub], rng)
    return res, int(m.sum())


def task(arg):
    date, (q, lam, noise) = arg
    name = cfg_name(q, lam, noise)
    path = RUNS / f"{date}__{name}.json"
    if path.exists():
        return str(path)
    T.low_priority()
    t_all = time.time()
    tt = T.Timetable()
    P = O.build_problem(tt, T.NH)
    pax = T.read_pax(date, tt)
    a = T.assign(pax, tt)
    x_true, B, A = T.truth_from_assignment(a, tt)
    true_frame = O.to_frame(P, x_true)
    Bn, An = B.copy(), A.copy()
    if noise:
        rng = np.random.default_rng(NOISE_SEED)
        Bn = Bn * np.clip(1 + noise * rng.standard_normal(len(Bn)), .5, None)
        An = An * np.clip(1 + noise * rng.standard_normal(len(An)), .5, None)
    spec = QS[q]
    g = O.hop_g(P, spec["kind"], beta=spec.get("beta"), truth_x=x_true, tilt=spec.get("tilt", 0.0))
    t_fit = time.time()
    qv = O.base_q(P, Bn, g)
    x, info = O.fit(P, Bn, An, qv, lam)
    fit_s = time.time() - t_fit
    est_frame = O.to_frame(P, x)
    ms = O.marginal_stats(P, est_frame, Bn, An)
    res_eval, n_eval = evaluate(P, true_frame, est_frame)
    res = dict(date=date, config=name, q=q, lam=lam, noise=noise, assignment=T.assignment_stats(a), n_eval_events=n_eval,
               true_total=float(x_true.sum()), est_total=float(x.sum()), input_B_total=float(Bn.sum()), input_A_total=float(An.sum()),
               fit=dict(seconds=fit_s, **info), marginal=ms, eval=res_eval, seconds_total=time.time() - t_all)
    if name == cfg_name("uniform", 0.01, 0.0):          # 정답 불확실성: Lout +-30초 정답 2종과 대조
        var = {}
        for sh in (-30.0, 30.0):
            av = T.assign(pax, tt, lout_shift=sh)
            xv, _, _ = T.truth_from_assignment(av, tt)
            fv = O.to_frame(P, xv)
            ev = P["ev"]
            m = ((ev.is_destination == 0) & ~ev.imputed_train & ~ev.low_signal_train).to_numpy()
            e = ev[m].reset_index(drop=True)
            rng = np.random.default_rng(SHUFFLE_SEED)
            vs_base = metrics(e, true_frame.load.to_numpy()[m], fv.load.to_numpy()[m], rng)      # 기준 정답 대비 변형 정답(정답끼리의 일치)
            vs_est = metrics(e, fv.load.to_numpy()[m], est_frame.load.to_numpy()[m], rng)        # 변형 정답 대비 역산 결과
            var[f"lout{int(sh):+d}"] = dict(used_pax=int(av.ok.sum()), truth_vs_base=vs_base, est_vs_variant_truth=vs_est)
        res["truth_uncertainty"] = var
    RUNS.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)


def summarize():
    rows = []
    for p in sorted(RUNS.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        for sub in ("all", "commute", "early_5_7", "midday_9_17", "evening_19_24", "toward_66", "toward_34"):
            m = r["eval"][sub]
            rows.append(dict(date=r["date"], q=r["q"], lam=r["lam"], noise=r["noise"], subset=sub, recovered=m["recovered"],
                             cell_spearman=m["cell"]["spearman"], cell_sum_ratio=m["cell"]["sum_ratio"], cell_top10_ratio=m["cell"]["top10pct_ratio"],
                             cell_mae_rel=m["cell"]["mae_rel"], train_spearman=m["train"]["spearman"], train_dev_corr=m["train"]["dev_corr"],
                             train_shuffle_dev=m["train"]["shuffle_dev_corr"], train_top1_ratio=m["train"]["top1pct_ratio"],
                             seg_rel_mae_med=m["train"]["seg_rel_mae_median"], fit_s=round(r["fit"]["seconds"], 1), converged=r["fit"]["converged"],
                             nit=r["fit"]["nit"], B_rel_l1=r["marginal"]["B_rel_l1_eligible"]))
    df = pd.DataFrame(rows)
    df.to_csv(T.OUT / "summary.csv", index=False, encoding="utf-8-sig")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all")
    ap.add_argument("--only")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--dates", default=",".join(DATES))
    a = ap.parse_args()
    if a.only:
        d, n = a.only.split(":")
        q, lam, noise = n.split("__")
        tasks = [(d, (q, float(lam[3:]), float(noise[1:])))]
    else:
        tasks = [(d, c) for d in a.dates.split(",") for c in all_configs(a.stage)]
    with Pool(min(a.workers, 3)) as pool:
        for r in pool.imap_unordered(task, tasks):
            print("done", Path(r).name, flush=True)
    summarize()
