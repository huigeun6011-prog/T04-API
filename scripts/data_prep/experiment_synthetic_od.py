"""합성 정답 OD에서 OD 방법(gt_train_od)과 Adam 방식(solve_day baseline)이 재차인원을 복원하는지 시험한다.
합성 자료만 사용한다(실제 피크 19건·production 파일 미사용). 설정은 outputs/diagnostics/synthetic_od/config.json(실행 전 고정).
  python experiment_synthetic_od.py [--only s2_gravity_mild:0.0] [--workers 3]
"""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
OUT = ROOT / "outputs/diagnostics/synthetic_od"
CFG = json.loads((OUT / "config.json").read_text(encoding="utf-8"))


def _low_priority():
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


def make_truth(P, sc, noise):
    ev, pa, pb, cell = P["ev"], P["pa"], P["pb"], P["cell"]
    K = len(P["slices"])
    tk = np.concatenate([np.full(e - s, k) for k, (s, e) in enumerate(P["slices"])])
    t0 = np.array([ev.minute[s] for s, _ in P["slices"]], float)
    if sc["w"] == "ones":
        w = np.ones(K)
    elif sc["w"] == "rush":
        w = 1 + 1.0 * np.exp(-((t0 - 495) / 45.0) ** 2) + 1.0 * np.exp(-((t0 - 1095) / 45.0) ** 2)
    else:
        w = np.exp(0.3 * np.random.default_rng(1).standard_normal(K))
    w = w / w.mean()
    nd = (ev.is_destination == 0).to_numpy()
    d = (pb - pa).astype(float)
    attr = ((P["A"][cell[pb]] + 1.0) if sc["attractiveness"] else np.ones(P["V"])) * np.exp(-sc["beta_d"] * d)
    z = np.bincount(pa, weights=attr, minlength=P["N"])
    pi = attr / np.maximum(z[pa], 1e-12)
    ok = (P["elig_b"] > 0) & (P["B"] > 0)
    den = np.bincount(cell, weights=w[tk] * nd, minlength=P["NC"] if "NC" in P else len(P["B"]))
    beta = np.where(ok & (den > 0), P["B"] / np.maximum(den, 1e-12), 0.0)
    m = w[tk] * beta[cell] * nd
    x = m[pa] * pi
    B = np.asarray(P["Mb"] @ x).ravel()
    A = np.asarray(P["Ma"] @ x).ravel()
    if noise:
        rng = np.random.default_rng(7)
        B = B * np.clip(1 + noise * rng.standard_normal(len(B)), .5, None)
        A = A * np.clip(1 + noise * rng.standard_normal(len(A)), .5, None)
    return x, B, A


def corr(a, b, how):
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return None
    r = pd.Series(a).rank().corr(pd.Series(b).rank()) if how == "s" else float(np.corrcoef(a, b)[0, 1])
    return None if pd.isna(r) else float(r)


def metrics(ev, true_load, est_load):
    nd = (ev.is_destination == 0).to_numpy()
    e = ev[nd].copy()
    e["t"], e["e"] = true_load[nd], est_load[nd]
    g = e.groupby(["station_idx", "hour_idx", "dir_code"])[["t", "e"]].mean()
    top = g.t >= g.t.quantile(0.9)
    top_ev = e.t >= e.t.quantile(0.99)
    e["tr"] = e.t - e.groupby(["station_idx", "hour_idx", "dir_code"]).t.transform("mean")
    e["er"] = e.e - e.groupby(["station_idx", "hour_idx", "dir_code"]).e.transform("mean")
    cell = dict(n=int(len(g)), spearman=corr(g.t.values, g.e.values, "s"), pearson=corr(g.t.values, g.e.values, "p"),
                sum_ratio=float(g.e.sum() / g.t.sum()), top10pct_ratio=float(g.e[top].sum() / g.t[top].sum()),
                mae_rel=float((g.e - g.t).abs().sum() / g.t.sum()))
    train = dict(n=int(len(e)), spearman=corr(e.t.values, e.e.values, "s"), pearson=corr(e.t.values, e.e.values, "p"),
                 sum_ratio=float(e.e.sum() / e.t.sum()), top1pct_ratio=float(e.e[top_ev].mean() / e.t[top_ev].mean()),
                 deviation_corr=corr(e.tr.values, e.er.values, "p"))
    ok = cell["spearman"] is not None and cell["spearman"] >= 0.9 and 0.9 <= cell["sum_ratio"] <= 1.1 and 0.8 <= cell["top10pct_ratio"] <= 1.2
    return dict(cell=cell, train=train, recovered=bool(ok))


def task(args):
    name, noise = args
    path = OUT / "runs" / f"{name}__{noise}.json"
    if path.exists():
        return str(path)
    _low_priority()
    import generate_ground_truth as gt
    import gt_train_od as od
    import gt_arrival_curve as ac
    t_all = time.time()
    P = od.build_problem(CFG["date"])
    x_true, B, A = make_truth(P, CFG["scenarios"][name], noise)
    ev = P["ev"]
    true_frame = od.to_frame(P, x_true)
    true_load = true_frame.load.to_numpy()
    P2 = dict(P); P2["B"], P2["A"] = B, A
    res = dict(scenario=name, noise=noise, true_total=float(x_true.sum()), input_B_total=float(B.sum()), input_A_total=float(A.sum()))
    # OD
    t = time.time()
    q = od.base_q(P2, "uniform", None, 1.0)
    x, info = od.fit(P2, q, 0.01)
    fr = od.to_frame(P2, x)
    ms = od.marginal_stats(P2, fr)
    res["od"] = dict(metrics(ev, true_load, fr.load.to_numpy()), seconds=time.time() - t, converged=info["converged"], nit=info["nit"],
                     B_rel_l1=ms["B_rel_l1_eligible"], A_rel_l1=ms["A_rel_l1_eligible"], est_total=float(x.sum()))
    # Adam baseline (입력 합계를 주입)
    t = time.time()
    ac.load_day = lambda d, B=B, A=A: (B.reshape(od.NS, od.NH).astype(np.float32), A.reshape(od.NS, od.NH).astype(np.float32))
    frame, _ = ac.solve_day(CFG["date"], mode="baseline", epochs=1000)
    assert (frame.train_id.to_numpy() == ev.train_id.to_numpy()).all() and (frame.station.to_numpy() == ev.station.to_numpy()).all()
    res["adam"] = dict(metrics(ev, true_load, frame.load.to_numpy()), seconds=time.time() - t)
    res["seconds_total"] = time.time() - t_all
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)


def summarize():
    rows = []
    for p in sorted((OUT / "runs").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        for est in ("od", "adam"):
            m = r[est]
            rows.append(dict(scenario=r["scenario"], noise=r["noise"], estimator=est, recovered=m["recovered"],
                             cell_spearman=m["cell"]["spearman"], cell_sum_ratio=m["cell"]["sum_ratio"], cell_top10_ratio=m["cell"]["top10pct_ratio"],
                             cell_mae_rel=m["cell"]["mae_rel"], train_spearman=m["train"]["spearman"], train_top1_ratio=m["train"]["top1pct_ratio"],
                             train_dev_corr=m["train"]["deviation_corr"], seconds=round(m["seconds"], 1)))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    print(df.round(3).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--workers", type=int, default=CFG["workers"])
    a = ap.parse_args()
    tasks = [(n, s) for n in CFG["scenarios"] for s in CFG["noise"]]
    if a.only:
        n, s = a.only.split(":")
        tasks = [(n, float(s))]
    with Pool(min(a.workers, 3), initializer=_low_priority) as pool:
        for r in pool.imap_unordered(task, tasks):
            print("done", r, flush=True)
    summarize()
