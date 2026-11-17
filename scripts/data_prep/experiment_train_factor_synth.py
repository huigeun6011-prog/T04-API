"""SYNTHETIC recovery test of a per-train crowding factor w_k (phase C). No real peak data; light CPU (<=3 workers, BELOW_NORMAL)."""
import os
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"
import ctypes, hashlib, json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gt_train_factor as tf
import generate_ground_truth as gt

OUT = gt.ROOT / "outputs/diagnostics/synthetic_train_factor"
DATE = "2025-11-04"
SCEN = ["a_rush", "b_lognormal", "c_null", "d_alternate"]
NOISES = [0.0, 0.02]
MAIN = dict(off=10.0, lam=0.01)
SENS = [(1.0, 0.01), (100.0, 0.01), (1.0, 0.1), (10.0, 0.1), (100.0, 0.1)]
MAXIT = dict(E1=6000, E2=3000, E3=3000)
CONFIG = dict(
    purpose="Synthetic recovery of per-train factor w_k from hourly cell marginals; real peak cases never read",
    date=DATE, model="x[k,a,b] = w_k * beta[cell(a)] * pi[a->b]; cell = station x stop-hour (gt_train_od convention)",
    pi_true="proportional to (A_obs[cell(b)]+1)*exp(-0.1*(b-a stops)), row normalized",
    beta_true="B_obs[cell] / sum of w over the cell's non-terminal events",
    scenarios={"a_rush": "w=1+1.0*exp(-((t-495)/45)^2)+1.0*exp(-((t-1095)/45)^2), t=origin departure minute (08:15=495, 18:15=1095)",
               "b_lognormal": "w=exp(0.3*z), z~N(0,1), seed 1", "c_null": "w=1",
               "d_alternate": "per direction, trains sorted by origin departure alternate 0.7/1.3 (even index 0.7, odd 1.3)",
               "all": "w normalized to mean 1"},
    noise="none or 2% multiplicative Gaussian per cell (seed 7), clipped at 0.5",
    estimators=dict(E1="pi = true, estimate w and beta (L-BFGS on log params, maxiter 6000)",
                    E2="pi free (per-event softmax logits) with lam*KL(pi||uniform) weighted by boarding mass; joint L-BFGS maxiter 3000; main off=10 lam=0.01",
                    E3="exploratory: shared kernel pi proportional to alpha[cell(b)]*exp(-delta*d), alpha/delta free, flat init, no KL; maxiter 3000"),
    fit_weights="(fit-obs)^2/(obs+off) per eligible cell", sensitivity_E2=SENS, sensitivity_scenarios=["a_rush", "b_lognormal"], sensitivity_noise=0.02,
    metrics=dict(within_hour_corr="subtract mean w within each origin-departure-hour group (both directions pooled) from w_hat and w_true, correlate",
                 peak_time_error="time of max 3-train moving average (same direction) of w_hat in [06:00,10:30] vs 08:15 and [16:00,20:30] vs 18:15"),
    decision_rules=dict(success="within-hour corr >= 0.9 in E2 at 2% noise for scenarios a, b, d (all three) => SUCCESS",
                        failure="all three < 0.5 => FAILURE; anything else PARTIAL (report which scenarios)",
                        null="scenario c at 2% noise: std(w_hat)/mean(w_hat) <= 0.05 else the method invents patterns (FAIL regardless)",
                        verdict_basis="E2 (declared realistic estimator); E1 and E3 are reported but do not decide"),
    resources="<=3 workers, OMP/MKL threads 1, BELOW_NORMAL priority, per-stage limit 15 min")


def lower_priority():
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


def progress(stage, **kw):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress.json").write_text(json.dumps(dict(stage=stage, time=time.strftime("%Y-%m-%d %H:%M:%S"), **kw)), encoding="utf-8")


def peak_err(P, w):
    out = {}
    for name, lo, hi, target in (("morning", 360, 630, 495), ("evening", 960, 1230, 1095)):
        best = None
        for d in (0, 1):
            idx = np.where((P["dir"] == d) & (P["t0"] >= lo) & (P["t0"] <= hi))[0]
            idx = idx[np.argsort(P["t0"][idx])]
            if len(idx) < 3:
                continue
            ma = np.convolve(w[idx], np.ones(3) / 3, "valid"); tm = np.convolve(P["t0"][idx], np.ones(3) / 3, "valid")
            i = ma.argmax()
            if best is None or ma[i] > best[0]:
                best = (ma[i], tm[i])
        out[f"peak_err_{name}_min"] = float(best[1] - target) if best else np.nan
    return out


def run_one(args):
    lower_priority()
    sc, noise, mode, off, lam = args
    P = tf.setup(DATE)
    T = tf.make_truth(P, sc, noise=noise)
    t0 = time.perf_counter()
    w, info = tf.fit(P, T["B"], T["A"], mode, T["pi"] if mode == "E1" else None, off, lam, MAXIT[mode])
    rush = tf.scenario_w(P, "a_rush")
    row = dict(scenario=sc, noise=noise, mode=mode, off=off, lam=lam, seconds=time.perf_counter() - t0,
               corr_all=float(np.corrcoef(w, T["w"])[0, 1]) if T["w"].std() > 1e-12 and w.std() > 1e-12 else np.nan,
               within_hour_corr=tf.within_hour_corr(P, w, T["w"]), within_hour_corr_dir=tf.within_hour_corr(P, w, T["w"], True),
               rel_err_median=float(np.median(np.abs(w - T["w"]) / T["w"])), rel_err_p90=float(np.quantile(np.abs(w - T["w"]) / T["w"], .9)),
               w_std_over_mean=float(w.std() / w.mean()), corr_with_rush_profile=float(np.corrcoef(w, rush)[0, 1]) if w.std() > 1e-12 else np.nan,
               **info)
    if sc == "a_rush":
        row.update(peak_err(P, w))
    return row


def step0():
    P = tf.setup(DATE); res = {}
    for sc in SCEN:
        T = tf.make_truth(P, sc)
        Jf, Jp = tf.jacobians(P, T)
        d = {}
        for name, J in (("fixed_beta_pi", Jf), ("profiled_beta", Jp)):
            U, S, Vt = np.linalg.svd(J, full_matrices=False)
            K = J.shape[1]
            delta = T["w"] - T["w"].mean(); hour = P["h0"]; wh = delta.copy()
            for g in np.unique(hour):
                wh[hour == g] -= delta[hour == g].mean()
            alt = np.where(np.argsort(np.argsort(P["t0"])) % 2 == 0, 1.0, -1.0)

            def recov(vec):
                c = Vt @ vec; snr = (c * S) ** 2
                return float((c ** 2 * snr / (1 + snr)).sum() / max((c ** 2).sum(), 1e-30))
            d[name] = dict(rows=int(J.shape[0]), cols=int(K), rank=int((S > S[0] * 1e-8).sum()), sigma_max=float(S[0]),
                           sigma_min=float(S[-1]), cond=float(S[0] / max(S[-1], 1e-300)), n_sigma_gt_1=int((S > 1).sum()),
                           n_sigma_gt_10=int((S > 10).sum()), n_sigma_gt_100=int((S > 100).sum()),
                           sigma_quantiles={str(q): float(np.quantile(S, q)) for q in (.05, .25, .5, .75, .95)},
                           pred_recoverable_total=recov(delta) if np.abs(delta).sum() > 0 else None,
                           pred_recoverable_within_hour=recov(wh) if np.abs(wh).sum() > 0 else None,
                           alt_contrast_recoverable=recov(alt - alt.mean()),
                           alt_contrast_energy_in_sigma_gt_1=float(((Vt[S > 1] @ (alt / np.linalg.norm(alt))) ** 2).sum()))
        res[sc] = d
    return res


def main():
    t_all = time.perf_counter()
    lower_priority(); OUT.mkdir(parents=True, exist_ok=True)
    CONFIG["source_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(tf.__file__), Path(__file__))}
    (OUT / "config.json").write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    progress("step0")
    s0 = step0(); (OUT / "step0_identifiability.json").write_text(json.dumps(s0, indent=1), encoding="utf-8")
    rows = []

    def stage(name, jobs):
        progress(name, n_jobs=len(jobs), elapsed_s=time.perf_counter() - t_all)
        t = time.perf_counter()
        with ProcessPoolExecutor(3) as ex:
            for r in ex.map(run_one, jobs):
                rows.append(r)
                pd.DataFrame(rows).to_csv(OUT / "results.csv", index=False, encoding="utf-8-sig")
                if time.perf_counter() - t > 900:
                    break
    stage("E1", [(s, n, "E1", 10.0, 0.0) for s in SCEN for n in NOISES])
    stage("E2_main", [(s, n, "E2", MAIN["off"], MAIN["lam"]) for s in SCEN for n in NOISES])
    stage("E3_exploratory", [(s, n, "E3", 10.0, 0.0) for s in SCEN for n in NOISES])
    stage("sensitivity", [(s, 0.02, "E2", o, l) for s in ("a_rush", "b_lognormal") for o, l in SENS]
          + [(s, 0.02, "E3", o, 0.0) for s in ("a_rush", "b_lognormal") for o in (1.0, 100.0)])
    progress("done", elapsed_s=time.perf_counter() - t_all)
    print(pd.DataFrame(rows)[["scenario", "noise", "mode", "off", "lam", "corr_all", "within_hour_corr", "w_std_over_mean", "rel_l1_A", "seconds"]].round(3).to_string())


if __name__ == "__main__":
    main()
