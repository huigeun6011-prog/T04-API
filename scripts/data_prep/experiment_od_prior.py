"""OD-derived direction prior experiment: same 6 days / seeds / 1000 Adam iterations as assumption_ablation
and queue_model. Peak cases are not read here (see validate_od_prior_peaks.py)."""
import argparse, hashlib, json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
import torch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
import gt_od_prior as od

CASES = {"2025-01-16": "before_weekday", "2025-01-18": "before_saturday",
         "2026-05-13": "after_weekday_with_past_same_weekday", "2026-05-16": "after_saturday_with_past_same_weekday",
         "2026-10-21": "ordinary_after_weekday", "2025-08-14": "midnight_gate_schedule_mismatch_possible"}
# ---- grid declared BEFORE any run; never changed after seeing results ------------------------------
BETAS, GAMMAS, LAMS = (0.1, 0.25), (1.0, 0.3), (0.1, 1.0)
ARM_CFG = {"baseline": None}
for b in BETAS:
    for g in GAMMAS:
        for l in LAMS:
            ARM_CFG[f"soft_grav_b{b}_g{g}_l{l}"] = dict(kind="soft", base="gravity", beta=b, gamma=g, lam=l)
        ARM_CFG[f"ipf_grav_b{b}_g{g}"] = dict(kind="ipf", base="gravity", beta=b, gamma=g)
for l in LAMS:
    ARM_CFG[f"soft_unif_l{l}"] = dict(kind="soft", base="uniform", beta=0, gamma=1, lam=l)
ARM_CFG["ipf_unif"] = dict(kind="ipf", base="uniform", beta=0, gamma=1)
ARMS = list(ARM_CFG)
SEEDS = [None, 11]
EPOCHS = 1000


def run_arm(arm, date, seed, epochs=EPOCHS):
    t0 = time.perf_counter(); diag = {}
    frame, aux = od.solve_day(date, ARM_CFG[arm], epochs, seed, diag)
    sec = time.perf_counter() - t0
    prev = frame.groupby("train_id", sort=False).raw_load.shift(fill_value=0)
    cons = float((frame.raw_load - prev - frame.board + frame.alight).abs().max())
    term = frame.loc[frame.is_destination == 1, "raw_load"].to_numpy()
    neg = np.minimum(frame.raw_load.to_numpy(), 0)
    row = dict(arm=arm, service_date=date, seed=seed, seconds=sec, raw_conservation_error_max=cons,
               terminal_mse=float(np.mean(term ** 2)), terminal_abs_p95=float(np.quantile(np.abs(term), .95)),
               negative_mse=float(np.mean(neg ** 2)), negative_stops=int((frame.raw_load < -.015).sum()),
               projection_total=float(-neg.sum()), raw_load_min=float(frame.raw_load.min()),
               board_slack=diag["board_observed_total"] - diag["board_allocated_total"],
               alight_slack=diag["alight_observed_total"] - diag["alight_allocated_total"],
               load_median=float(frame.load.median()), load_p95=float(frame.load.quantile(.95)),
               load_p99=float(frame.load.quantile(.99)), load_max=float(frame.load.max()),
               **{k: v for k, v in diag.items() if k.endswith("_static") or k.endswith("_hat")})
    return row, aux


def _job(a):
    row, aux = run_arm(*a)
    return row, {k: aux[k] for k in ("p_fit", "p_hat", "q_hat", "B")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=gt.ROOT / "outputs/diagnostics/od_prior")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    src = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
           (Path(gt.__file__), Path(od.__file__), Path(__file__))}
    cfg = dict(purpose="OD-derived direction prior in baseline optimizer; peak cases not read", cases=CASES, seeds=SEEDS,
               epochs=EPOCHS, patience=0, optimizer="Adam lr .1; logit noise std .25 for seed 11 (as ablation); prior and init = p_hat/q_hat",
               grid=dict(betas=BETAS, gammas=GAMMAS, lams=LAMS), arms={k: v for k, v in ARM_CFG.items()},
               base="gravity q_ij=exp(-beta*d)*(gamma if d==1)*B_i*A_j ; uniform control q_ij=B_i*A_j ; d=|i-j| stops",
               scaling="B,A divided by mean marginal (sum B + sum A)/(2*22); q rescaled to marginal mass; soft objective sum squared marginal residuals + lam*generalized KL(x||q)",
               direction="dir_code0=up toward index0; p_hat=sum_{j<i}x_ij/rowsum; q_hat=sum_{i>j}x_ij/colsum; fallback to static prior if flow<0.05 scaled units",
               source_sha256=src)
    (a.out / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    jobs = [(arm, d, s, EPOCHS) for d in CASES for arm in ARMS for s in SEEDS]
    t0 = time.perf_counter(); rows, store = [], {}
    with ProcessPoolExecutor(a.workers) as ex:
        for job, (row, aux) in zip(jobs, ex.map(_job, jobs)):
            rows.append(row)
            store[f"{job[0]}|{job[1]}|{job[2]}"] = aux
            print(json.dumps({k: row[k] for k in ("arm", "service_date", "seed", "terminal_mse", "negative_mse")}), flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(a.out / "results.csv", index=False, encoding="utf-8-sig")
    np.savez_compressed(a.out / "pq_arrays.npz", **{f"{k}|{n}": v for k, aux in store.items() for n, v in aux.items()})
    cols = ["terminal_mse", "terminal_abs_p95", "negative_mse", "negative_stops", "board_slack", "alight_slack",
            "raw_conservation_error_max", "load_median", "load_p95", "load_p99", "load_max", "p_dev_from_static",
            "p_dev_from_hat", "p_hat_dev_from_static", "q_dev_from_static", "q_dev_from_hat", "seconds"]
    for name, sel in (("normal5", df.service_date != "2025-08-14"), ("midnight_day", df.service_date == "2025-08-14")):
        df[sel].groupby("arm")[cols].mean().reindex(ARMS).to_csv(a.out / f"summary_{name}.csv", encoding="utf-8-sig")
    (a.out / "elapsed.json").write_text(json.dumps({"seconds": time.perf_counter() - t0}))
    print(df[df.service_date != "2025-08-14"].groupby("arm")[cols[:4]].mean().reindex(ARMS).round(2).to_string())


if __name__ == "__main__":
    main()
