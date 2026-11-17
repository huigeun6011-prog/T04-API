"""Train-level OD experiment vs the baseline generator on the same 6 days. Peak cases not read here."""
import argparse, hashlib, json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
import gt_arrival_curve as ac
import gt_train_od as od
from experiment_queue_model import CASES

# ---- declared before running; never changed after results -------------------------------------------
LAMS = (0.01, 0.1)      # lambda=1.0 was smoke-tested once on one day: ~20% alighting misfit, dropped as too strong
BETAS, GAMMAS = (0.1, 0.25), (1.0, 0.3)
ARM_CFG = {"baseline": None}
for l in LAMS:
    ARM_CFG[f"od_uniform_l{l}"] = dict(weight="uniform", beta=None, gamma=1.0, lam=l)
    ARM_CFG[f"od_headway_l{l}"] = dict(weight="headway", beta=None, gamma=1.0, lam=l)
    for b in BETAS:
        for g in GAMMAS:
            ARM_CFG[f"od_gravity_b{b}_g{g}_l{l}"] = dict(weight="uniform", beta=b, gamma=g, lam=l)
ARMS = list(ARM_CFG)
SEEDS = [None, 11]     # baseline only; OD arms are deterministic (init = base q)
EPOCHS = 1000
# combined score: TNV = (L1 marginal misfit incl. slack cells + L1 terminal residual + L1 negative load) / (sum B + sum A)


def stats(P, frame):
    ms = od.marginal_stats(P, frame)
    term, neg = od.physical_l1(frame)
    tot = ms["B_total_obs"] + ms["A_total_obs"]
    f = frame[frame.is_destination == 0]
    g = f.groupby(["station_idx", "hour", "dir_code"]).board.agg(["mean", "std", "count"])
    g = g[(g["count"] >= 3) & (g["mean"] >= 20)]
    t = frame.loc[frame.is_destination == 1, "raw_load"].to_numpy()
    return dict(terminal_mse=float(np.mean(t ** 2)), terminal_abs_p95=float(np.quantile(np.abs(t), .95)),
                negative_mse=float(np.mean(np.minimum(frame.raw_load, 0) ** 2)), negative_stops=int((frame.raw_load < -.015).sum()),
                terminal_l1=term, negative_l1=neg, **ms,
                marginal_l1_misfit=ms["B_l1_all"] + ms["A_l1_all"], marginal_rel_misfit=(ms["B_l1_all"] + ms["A_l1_all"]) / tot,
                physical_rel=(term + neg) / tot, TNV=(ms["B_l1_all"] + ms["A_l1_all"] + term + neg) / tot,
                cv_board_median=float((g["std"] / g["mean"]).median()),
                load_median=float(frame.load.median()), load_p95=float(frame.load.quantile(.95)), load_p99=float(frame.load.quantile(.99)),
                load_mean=float(frame.load.mean()), peak_hr_load_mean=float(frame[frame.hour.isin([8, 18])].load.mean()))


def run_arm(arm, date, seed, keep_frame=False):
    t0 = time.perf_counter(); P = od.build_problem(date); info = {}
    if arm == "baseline":
        frame, _ = ac.solve_day(date, "baseline", 1.0, EPOCHS, seed, {})
    else:
        c = ARM_CFG[arm]
        x, info = od.fit(P, od.base_q(P, c["weight"], c["beta"], c["gamma"]), c["lam"])
        frame = od.to_frame(P, x)
    sec = time.perf_counter() - t0
    row = dict(arm=arm, service_date=date, seed=seed, seconds=sec, **stats(P, frame), solver_iters=info.get("nit"),
               solver_converged=info.get("converged"), solver_proj_grad=info.get("proj_grad_inf"))
    key = frame.groupby(["station_idx", "hour", "dir_code"]).load.mean()
    if keep_frame:
        return row, frame
    return row, key


def _job(a):
    return run_arm(*a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=gt.ROOT / "outputs/diagnostics/train_od"); ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args(); a.out.mkdir(parents=True, exist_ok=True)
    cfg = dict(purpose="Train-level OD with soft hourly marginals, hard conservation; peak cases not read", cases=CASES,
               baseline_seeds=SEEDS, baseline_epochs=EPOCHS, lambdas=LAMS, betas=BETAS, gammas=GAMMAS, arms=ARM_CFG,
               objective="sum_cells (fit-obs)^2/(obs+10) + lam * generalized KL(x||q); L-BFGS-B on x>=1e-12, maxiter 20000",
               base_q="boarding cell mass = B(s,h) split by train weight (uniform | headway gap minutes) over events of the cell, then over later stops by exp(-beta*d)*(gamma if d==1) (uniform when beta None)",
               combined_score="TNV = (L1 marginal misfit incl. no-train slack cells + L1 terminal residual + L1 negative load) / (sum B + sum A)",
               source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(gt.__file__), Path(ac.__file__), Path(od.__file__), Path(__file__))})
    (a.out / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    jobs = [(arm, d, s) for d in CASES for arm in ARMS for s in (SEEDS if arm == "baseline" else [None])]
    t0 = time.perf_counter(); rows = []; keys = {}
    with ProcessPoolExecutor(a.workers) as ex:
        for job, (row, key) in zip(jobs, ex.map(_job, jobs)):
            rows.append(row); keys[(job[0], job[1], job[2])] = key
            print(json.dumps({k: row[k] for k in ("arm", "service_date", "seed", "TNV", "terminal_mse", "seconds")}), flush=True)
    for r in rows:     # rank correlation of per (station,hour,direction) mean load with the baseline (seed none) pattern
        base = keys[("baseline", r["service_date"], None)]; mine = keys[(r["arm"], r["service_date"], r["seed"])]
        j = pd.concat([base, mine], axis=1, keys=["b", "m"]).dropna()
        r["spearman_vs_baseline"] = float(spearmanr(j.b, j.m)[0])
    df = pd.DataFrame(rows); df.to_csv(a.out / "results.csv", index=False, encoding="utf-8-sig")
    cols = [c for c in df.columns if c not in ("arm", "service_date", "seed", "solver_converged")]
    for name, sel in (("normal5", df.service_date != "2025-08-14"), ("midnight_day", df.service_date == "2025-08-14")):
        df[sel].groupby("arm")[cols].mean().reindex(ARMS).to_csv(a.out / f"summary_{name}.csv", encoding="utf-8-sig")
    (a.out / "elapsed.json").write_text(json.dumps({"seconds": time.perf_counter() - t0}))


if __name__ == "__main__":
    main()
