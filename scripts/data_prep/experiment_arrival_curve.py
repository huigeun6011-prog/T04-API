"""Arrival-curve experiment: same 6 days / seeds / 1000 Adam iterations as assumption_ablation, queue_model, od_prior.
Peak cases are not read here (validate_arrival_curve_peaks.py is the single post-hoc step)."""
import argparse, hashlib, json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd, torch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
import gt_arrival_curve as ac
from gt_assumptions import AssumptionConfig
from experiment_queue_model import CASES

# ---- arms declared BEFORE running any curve arm; never changed after results ---------------------------
ARM_CFG = {
    "baseline": dict(impl="ac", mode="baseline"),
    "headway_uniform_existing": dict(impl="gt"),
    "curve_d1": dict(impl="ac", mode="d1", mix=1.0),
    "curve_d2": dict(impl="ac", mode="d2", mix=1.0),
    "curve_d2_mix50": dict(impl="ac", mode="d2", mix=0.5),
}
ARMS = list(ARM_CFG)
SEEDS = [None, 11]
EPOCHS = 1000


def run_arm(arm, date, seed, epochs=EPOCHS, keep_frame=False):
    cfg = ARM_CFG[arm]; t0 = time.perf_counter(); diag = {}
    if cfg["impl"] == "gt":
        nxt = (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        frame = pd.DataFrame(gt.process_single_date(date, gt.SUBWAY_DIR / f"{date}.json", gt.SUBWAY_DIR / f"{nxt}.json",
                             gt.WEATHER_DIR / f"{date}.json", torch.device("cpu"), epochs=epochs, patience=0, init_seed=seed,
                             diagnostics=diag, assumptions=AssumptionConfig(boarding_headway=True)))
        aux = dict(B=ac.load_day(date)[0], cum=None, p_fit=None)
        diag["unallocated"] = None
    else:
        frame, aux = ac.solve_day(date, cfg["mode"], cfg.get("mix", 1.0), epochs, seed, diag)
    sec = time.perf_counter() - t0
    prev = frame.groupby("train_id", sort=False).raw_load.shift(fill_value=0)
    cons = float((frame.raw_load - prev - frame.board + frame.alight).abs().max())
    term = frame.loc[frame.is_destination == 1, "raw_load"].to_numpy(); neg = np.minimum(frame.raw_load.to_numpy(), 0)
    f = frame[frame.is_destination == 0]; g = f.groupby(["station_idx", "hour", "dir_code"])
    st = g.board.agg(["mean", "std", "count"]); st = st[(st["count"] >= 3) & (st["mean"] >= 20)]
    cv_b = st["std"] / st["mean"]
    bslack = diag["board_observed_total"] - diag["board_allocated_total"]
    row = dict(arm=arm, service_date=date, seed=seed, seconds=sec, raw_conservation_error_max=cons,
               terminal_mse=float(np.mean(term ** 2)), terminal_abs_p95=float(np.quantile(np.abs(term), .95)),
               negative_mse=float(np.mean(neg ** 2)), negative_stops=int((frame.raw_load < -.015).sum()),
               board_slack=float(bslack), board_slack_frac=float(bslack / diag["board_observed_total"]),
               alight_slack=float(diag["alight_observed_total"] - diag["alight_allocated_total"]),
               cv_board_median=float(cv_b.median()), cv_board_mean=float(cv_b.mean()),
               load_median=float(frame.load.median()), load_p95=float(frame.load.quantile(.95)),
               load_p99=float(frame.load.quantile(.99)), load_max=float(frame.load.max()),
               load_mean=float(frame.load.mean()),
               peak_hr_load_mean=float(frame[frame.hour.isin([8, 18])].load.mean()))
    if aux.get("cum") is not None and seed is None:       # curve shape vs flat, top-5 boarding stations in the 8h bucket
        B, cum = aux["B"], aux["cum"]
        top = np.argsort(-B[:, 8 - 5])[:5]
        h = 8 - 5
        last20 = [(cum[s, (h + 1) * 60] - cum[s, h * 60 + 40]) / max(B[s, h], 1e-9) for s in top]
        first20 = [(cum[s, h * 60 + 20] - cum[s, h * 60]) / max(B[s, h], 1e-9) for s in top]
        row.update(top5_8h_share_last20=float(np.mean(last20)), top5_8h_share_first20=float(np.mean(first20)))
    return (row, frame) if keep_frame else row


def _job(a):
    return run_arm(*a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=gt.ROOT / "outputs/diagnostics/arrival_curve")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args(); a.out.mkdir(parents=True, exist_ok=True)
    cfg = dict(purpose="Mass-preserving arrival curve vs uniform headway; peak cases not read", cases=CASES, seeds=SEEDS,
               epochs=EPOCHS, patience=0, optimizer="Adam lr .1; logit noise std .25 for seed 11 (as ablation)", arms=ARM_CFG,
               curve=dict(grid="1-minute cells 05:00..25:00", constraint="exact hourly sums, hours with B=0 are 0, nonneg",
                          smoothness={"d1": "sum squared first differences", "d2": "sum squared second differences"},
                          boundary="free ends (no penalty outside 05:00-25:00); window of first departure starts 05:00; mass after last departure = slack",
                          mix="curve_d2_mix50 = 0.5*curve_d2 + 0.5*flat (both mass preserving)", solver="primal active-set, sparse KKT"),
               source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                              (Path(gt.__file__), Path(ac.__file__), Path(__file__))})
    (a.out / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    jobs = [(arm, d, s, EPOCHS) for d in CASES for arm in ARMS for s in SEEDS]
    t0 = time.perf_counter(); rows = []
    with ProcessPoolExecutor(a.workers) as ex:
        for r in ex.map(_job, jobs):
            rows.append(r); print(json.dumps({k: r[k] for k in ("arm", "service_date", "seed", "terminal_mse", "board_slack")}), flush=True)
    df = pd.DataFrame(rows); df.to_csv(a.out / "results.csv", index=False, encoding="utf-8-sig")
    cols = [c for c in df.columns if c not in ("arm", "service_date", "seed")]
    for name, sel in (("normal5", df.service_date != "2025-08-14"), ("midnight_day", df.service_date == "2025-08-14")):
        df[sel].groupby("arm")[cols].mean().reindex(ARMS).to_csv(a.out / f"summary_{name}.csv", encoding="utf-8-sig")
    (a.out / "elapsed.json").write_text(json.dumps({"seconds": time.perf_counter() - t0}))
    print(df[df.service_date != "2025-08-14"].groupby("arm")[["terminal_mse", "negative_mse", "board_slack", "load_mean", "peak_hr_load_mean"]].mean().reindex(ARMS).round(2).to_string())


if __name__ == "__main__":
    main()
