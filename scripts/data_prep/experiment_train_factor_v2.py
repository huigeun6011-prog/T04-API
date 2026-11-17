"""Phase D: more tests of the per-train crowding factor on SYNTHETIC data (exact LM/NNLS solvers, day pooling,
low-dimensional/smooth w, unknown kernel, resolution view). Light CPU (3 workers, BELOW_NORMAL). No real peak data."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import ctypes, hashlib, json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gt_train_factor as tf
import gt_train_factor_v2 as v2
import generate_ground_truth as gt

OUT = gt.ROOT / "outputs/diagnostics/synthetic_train_factor_v2"
DATE = "2025-11-04"
SCEN = ["a_rush", "b_lognormal", "c_null", "d_alternate"]
NOISES = [0.0, 0.02, 0.05]
BASES = [6, 12, 24]
CONFIG = dict(
    purpose="Synthetic recovery of per-train factor w_k; convex/exact solvers; real peak cases never read",
    date=DATE, scenarios="same as phase C: a_rush, b_lognormal(seed1), c_null, d_alternate (=trap e_sharp); w normalized mean 1",
    truth="x = w_k beta[cell a] pi[a->b]; pi_true main = (A_obs[cell b]+1)*exp(-0.1 d); misspecified truth = station-level attraction (hour ignored) * (1+d)^-1.5",
    days="K synthetic weekdays share the timetable and w; each day: beta = day_factor(lognormal sd .1, K>1) * base, independent 2%/5% multiplicative noise per cell; pi_perturb variant: per-day lognormal sd .1 on pi pairs (estimator uses nominal pi)",
    noises=NOISES, methods={
        "D0_oracle_beta": "beta known, pi known, free w, exact bounded LS (K=1)",
        "D1_free": "beta profiled from B per day (exact), pi known, free w, Levenberg-Marquardt Gauss-Newton with exact Jacobian; K in {1,5,20} (+60 for a,b at 2/5%)",
        "D2_smooth": "as D1 with second-difference penalty on w per direction (gamma=0.1*mean diag info), K in {1,20}",
        "D2_basis{m}": "w = Phi c, cubic B-spline over origin departure time, m in {6,12,24}, smoothness rho=0.01 on 2nd diff of c, K in {1,20}",
        "D3": "basis 24, kernel alpha[cell(b)]*exp(-delta d) estimated by alternating LM / L-BFGS (flat init), noise 2%: truth main, truth misspecified (kernel est.), truth misspecified with the WRONG fixed main pi",
        "D1/D2 pi_perturb": "K=20, noise 2%, free and basis24, scenarios a,b,c",
        "offset_sensitivity": "off in {1,10,100} for D1_free K=1 and basis24 K=1, scenarios a,b,c, noise 2%"},
    ridge_to_one="eps=1e-4 * mean diag information, pulls w toward 1 (null hypothesis)",
    metrics="corr, within-hour corr (origin-hour groups), bin-mean corr at 60/30/15/5 min of origin departure, relative error of bin means, std/mean of w_hat",
    decision_rules=dict(
        success="30-min-bin corr >= 0.9 for the scenario AND std(w_hat)/mean(w_hat) <= 0.05 in c_null for the same method/K/noise",
        finest_bin="finest bin width in {60,30,15,5} with bin corr >= 0.9, per (method,K,noise,scenario); none => not recoverable at any tested width",
        categories="(i) per-train recoverable: within-hour corr >= 0.9; (ii) recoverable only at coarse resolution: state finest bin width; (iii) not recoverable"),
    resources="<=3 workers, threads 1, BELOW_NORMAL, per-stage limit 15 min",
    note="basis grid changed from the brief's {4,6,8,12} to {6,12,24} because a cubic basis with <=12 functions cannot represent the 45-minute rush bumps (projection corr 0.69 at m=8, 0.87 at m=12, 0.996 at m=24, checked before running)")


def lower_priority():
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


def progress(stage, **kw):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress.json").write_text(json.dumps(dict(stage=stage, time=time.strftime("%Y-%m-%d %H:%M:%S"), **kw)), encoding="utf-8")


def job(spec):
    lower_priority()
    P = tf.setup(DATE)
    truth_mode = spec.get("truth", "main")
    wt, days = v2.make_days(P, spec["scen"], spec["K"], spec["noise"], truth_mode, spec.get("pi_perturb", 0.0))
    kw = dict(off=spec.get("off", 10.0), beta_mode=spec.get("beta_mode", "est"), basis=spec.get("basis", 0), gamma=spec.get("gamma", 0.0),
              pi_mode=spec.get("pi_mode", "fixed"), outer=spec.get("outer", 1))
    if spec.get("pi_wrong"):
        kw["pi_fixed"] = tf.pi_true(P)
    t0 = time.perf_counter()
    w, info = v2.estimate(P, days, **kw)
    row = dict(spec, seconds=time.perf_counter() - t0, **info)
    sd = wt.std()
    row.update(corr_all=float(np.corrcoef(w, wt)[0, 1]) if sd > 1e-12 and w.std() > 1e-12 else np.nan,
               within_hour_corr=tf.within_hour_corr(P, w, wt), w_std_over_mean=float(w.std() / w.mean()), **v2.binned_metrics(P, w, wt))
    return row


def build_stages():
    st = {}
    st["D0"] = [dict(method="D0_oracle_beta", scen=s, K=1, noise=n, beta_mode="oracle") for s in SCEN for n in NOISES]
    st["D1"] = [dict(method="D1_free", scen=s, K=K, noise=n) for K in (1, 5, 20) for s in SCEN for n in NOISES]
    st["D1"] += [dict(method="D1_free", scen=s, K=60, noise=n) for s in SCEN for n in (0.02, 0.05)]
    st["D2"] = [dict(method="D2_smooth", scen=s, K=K, noise=n, gamma=0.1) for K in (1, 20) for s in SCEN for n in NOISES]
    st["D2"] += [dict(method=f"D2_basis{m}", scen=s, K=K, noise=n, basis=m) for m in BASES for K in (1, 20) for s in SCEN for n in NOISES]
    st["extra"] = [dict(method="D1_free_pi_perturb", scen=s, K=20, noise=0.02, pi_perturb=0.1) for s in ("a_rush", "b_lognormal", "c_null")]
    st["extra"] += [dict(method="D2_basis24_pi_perturb", scen=s, K=20, noise=0.02, pi_perturb=0.1, basis=24) for s in ("a_rush", "b_lognormal", "c_null")]
    st["extra"] += [dict(method=f"{m}_off{o}", scen=s, K=1, noise=0.02, off=o, **({} if m == "D1_free" else dict(basis=24)))
                    for m in ("D1_free", "D2_basis24") for o in (1.0, 100.0) for s in ("a_rush", "b_lognormal", "c_null")]
    d3 = []
    for s in SCEN:
        d3.append(dict(method="D3_kernel_est_truth_main", scen=s, K=1, noise=0.02, basis=24, pi_mode="kernel", outer=4))
        d3.append(dict(method="D3_kernel_est_truth_misspec", scen=s, K=1, noise=0.02, basis=24, pi_mode="kernel", outer=4, truth="misspec"))
        d3.append(dict(method="D3_wrong_fixed_pi_truth_misspec", scen=s, K=1, noise=0.02, basis=24, truth="misspec", pi_wrong=True))
    d3 += [dict(method="D3_kernel_est_truth_main", scen=s, K=20, noise=0.02, basis=24, pi_mode="kernel", outer=3) for s in ("a_rush", "c_null")]
    st["D3"] = d3
    return st


def summarize(df):
    df = df.copy()
    key = ["method", "K", "noise", "off", "pi_perturb", "truth"]
    for c, d in (("off", 10.0), ("pi_perturb", 0.0), ("truth", "main")):
        if c not in df: df[c] = d
        df[c] = df[c].fillna(d)
    null = df[df.scen == "c_null"].set_index(key).w_std_over_mean.rename("null_std")
    out = df.join(null, on=key)
    def finest(r):
        ok = [wd for wd in (5, 15, 30, 60) if r.get(f"bin{wd}_corr", np.nan) >= 0.9]
        return ok[0] if ok else np.nan
    out["finest_bin_ge0.9"] = out.apply(finest, axis=1)
    out["success_30min"] = (out["bin30_corr"] >= 0.9) & (out["null_std"] <= 0.05)
    out["category"] = np.where(out.within_hour_corr >= 0.9, "i_per_train", np.where(out["finest_bin_ge0.9"].notna(), "ii_coarse", "iii_none"))
    out.loc[out.scen == "c_null", "category"] = "null"
    return out


def main():
    t_all = time.perf_counter(); lower_priority(); OUT.mkdir(parents=True, exist_ok=True)
    CONFIG["source_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(tf.__file__), Path(v2.__file__), Path(__file__))}
    (OUT / "config.json").write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for name, jobs in build_stages().items():
        progress(name, n_jobs=len(jobs), elapsed_s=time.perf_counter() - t_all)
        t = time.perf_counter()
        with ProcessPoolExecutor(3) as ex:
            futs = [ex.submit(job, j) for j in jobs]
            for f in futs:
                try:
                    rows.append(f.result(timeout=max(1, 900 - (time.perf_counter() - t))))
                except Exception as e:
                    rows.append(dict(error=str(e)[:200])); break
                pd.DataFrame(rows).to_csv(OUT / "results.csv", index=False, encoding="utf-8-sig")
            for f in futs:
                f.cancel()
        progress(name + "_done", elapsed_s=time.perf_counter() - t_all)
    df = summarize(pd.DataFrame(rows)); df.to_csv(OUT / "results_summarized.csv", index=False, encoding="utf-8-sig")
    progress("done", elapsed_s=time.perf_counter() - t_all)


if __name__ == "__main__":
    main()
