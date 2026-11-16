"""Queue/capacity boarding experiment on the SAME 6 days / seeds / 1000 Adam iterations as the
assumption ablation. No peak-case data is read here (see validate_queue_peaks.py for the one post-hoc step).

Capacity: official train spec ("정원") is not in docs/. It is implied by the congestion definition in
the supplied congestion file (재차인원/혼잡도% is constant ~4.746 persons per %  => 정원 ~ 475). Only that
CONSTANT is used (hard-coded below, frozen before any model output was seen); no per-case load is used.
Crush capacities declared in advance: 1.0x, 1.5x, 2.0x of 정원 (round multiples, not tuned).
"""
import argparse, hashlib, json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
import torch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
import gt_assumptions
import gt_queue_model as qm
from gt_assumptions import AssumptionConfig

CASES = {"2025-01-16": "before_weekday", "2025-01-18": "before_saturday",
         "2026-05-13": "after_weekday_with_past_same_weekday", "2026-05-16": "after_saturday_with_past_same_weekday",
         "2026-10-21": "ordinary_after_weekday", "2025-08-14": "midnight_gate_schedule_mismatch_possible"}
SEATED_CAP = 475.0  # 정원 implied by the official congestion definition
CAPS = {"queue_C1.0x_475": SEATED_CAP, "queue_C1.5x_713": round(1.5 * SEATED_CAP), "queue_C2.0x_950": 2.0 * SEATED_CAP}
ARMS = ["baseline", "boarding_headway"] + list(CAPS)
SEEDS = [None, 11]
EPOCHS = 1000


def run_arm(arm, date, seed, epochs=EPOCHS, keep_frame=False):
    torch.set_num_threads(1)
    t0 = time.perf_counter()
    diag = {}
    if arm in CAPS or arm == "queue_inf":
        frame = qm.solve_day(date, CAPS.get(arm), epochs, seed, diag)
        slack_b = diag["board_observed_total"] - diag["board_allocated_total"]
        slack_a = diag["alight_observed_total"] - diag["alight_allocated_total"]
        carry = diag["board_leftover_queue_end_of_day"]
        epochs_run = diag["epochs_run"]
    else:
        nxt = (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        cfg = AssumptionConfig(boarding_headway=(arm == "boarding_headway"))
        recs = gt.process_single_date(date, gt.SUBWAY_DIR / f"{date}.json", gt.SUBWAY_DIR / f"{nxt}.json",
                                      gt.WEATHER_DIR / f"{date}.json", torch.device("cpu"), epochs=epochs, patience=0,
                                      init_seed=seed, diagnostics=diag, assumptions=cfg)
        frame = pd.DataFrame(recs)
        slack_b = diag["board_observed_total"] - diag["board_allocated_total"]
        slack_a = diag["alight_observed_total"] - diag["alight_allocated_total"]
        carry = 0.0
        epochs_run = diag["epochs_run"]
    sec = time.perf_counter() - t0
    prev = frame.groupby("train_id", sort=False).raw_load.shift(fill_value=0)
    cons = float((frame.raw_load - prev - frame.board + frame.alight).abs().max())
    term = frame.loc[frame.is_destination == 1, "raw_load"].to_numpy()
    neg = np.minimum(frame.raw_load.to_numpy(), 0)
    # dispersion across same-direction trains in the same station-hour (non-terminal stops, >=3 trains, mean board >=20)
    f = frame[frame.is_destination == 0]
    g = f.groupby(["station_idx", "hour", "dir_code"])
    st = g.board.agg(["mean", "std", "count"])
    st = st[(st["count"] >= 3) & (st["mean"] >= 20)]
    cv_b = (st["std"] / st["mean"])
    gl = g.load.agg(["mean", "std", "count"]).loc[st.index]
    cv_l = (gl["std"] / gl["mean"].clip(lower=1e-9))
    row = dict(arm=arm, service_date=date, case=CASES.get(date), seed=seed, seconds=sec, epochs_run=epochs_run,
               raw_conservation_error_max=cons, terminal_mse=float(np.mean(term ** 2)),
               terminal_abs_p95=float(np.quantile(np.abs(term), .95)), negative_mse=float(np.mean(neg ** 2)),
               negative_stops=int((frame.raw_load < -.015).sum()), raw_load_min=float(frame.raw_load.min()),
               projection_total=float(-neg.sum()), board_slack=float(slack_b), alight_slack=float(slack_a),
               end_of_day_queue_left=float(carry), board_observed=diag["board_observed_total"],
               cv_board_median=float(cv_b.median()), cv_board_mean=float(cv_b.mean()),
               cv_load_median=float(cv_l.median()), n_groups=int(len(st)),
               max_load_raw=float(frame.raw_load.max()), p99_load=float(frame.load.quantile(.99)),
               max_board=float(frame.board.max()))
    return (row, frame) if keep_frame else row


def _job(args):
    return run_arm(*args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=gt.ROOT / "outputs/diagnostics/queue_model")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    src = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
           (Path(gt.__file__), Path(gt_assumptions.__file__), Path(qm.__file__), Path(__file__))}
    cfg = dict(purpose="Queue+capacity boarding experiment; peak cases not read", cases=CASES, seeds=SEEDS,
               epochs=a.epochs, patience=0, optimizer="Adam lr .1, logit noise std .25 for seed 11 (as ablation)",
               capacities=CAPS, seated_capacity_basis="constant ratio of 재차인원/혼잡도% in the official congestion file (~4.746/%), frozen constant 475",
               softmin_eps_persons=qm.EPS, arms=ARMS, source_sha256=src)
    (a.out / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    jobs = [(arm, d, s, a.epochs) for d in CASES for arm in ARMS for s in SEEDS]
    t0 = time.perf_counter()
    rows = []
    with ProcessPoolExecutor(a.workers) as ex:
        for r in ex.map(_job, jobs):
            rows.append(r)
            print(json.dumps({k: r[k] for k in ("arm", "service_date", "seed", "seconds", "terminal_mse", "board_slack")}), flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(a.out / "results.csv", index=False, encoding="utf-8-sig")
    normal = df[df.service_date != "2025-08-14"]
    cols = ["terminal_mse", "terminal_abs_p95", "negative_mse", "negative_stops", "board_slack", "alight_slack",
            "end_of_day_queue_left", "cv_board_median", "cv_load_median", "raw_conservation_error_max", "seconds", "max_board", "p99_load"]
    summ = normal.groupby("arm")[cols].mean().reindex(ARMS)
    mid = df[df.service_date == "2025-08-14"].groupby("arm")[cols].mean().reindex(ARMS)
    summ.to_csv(a.out / "summary_normal5.csv", encoding="utf-8-sig")
    mid.to_csv(a.out / "summary_midnight_day.csv", encoding="utf-8-sig")
    (a.out / "elapsed.json").write_text(json.dumps({"seconds": time.perf_counter() - t0}))
    print(summ.round(3).to_string()); print(mid.round(3).to_string())


if __name__ == "__main__":
    main()
