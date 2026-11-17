"""Step 1 diagnosis: where does uniform-headway boarding mass go, and why do peak loads drop vs baseline?
No peak cases used. Run: .venv/Scripts/python.exe scripts/data_prep/diagnose_headway_mass.py"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, torch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
from gt_assumptions import AssumptionConfig
from experiment_queue_model import CASES

OUT = gt.ROOT / "outputs/diagnostics/arrival_curve"
HOURS = gt.HOURS


def obs(date):
    nxt = (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cur = json.loads((gt.SUBWAY_DIR / f"{date}.json").read_text(encoding="utf-8"))["stations"]
    nd = json.loads((gt.SUBWAY_DIR / f"{nxt}.json").read_text(encoding="utf-8"))["stations"]
    B = np.zeros((22, 20))
    for sid, s in cur.items():
        if 101 <= int(sid) <= 122:
            for h, c in s["boardings"].items():
                if 5 <= int(h) <= 23: B[int(sid) - 101, int(h) - 5] += c
    for sid, s in nd.items():
        if 101 <= int(sid) <= 122: B[int(sid) - 101, 19] += s["boardings"].get("0", 0)
    return B


def run(date, headway):
    nxt = (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"); d = {}
    rec = gt.process_single_date(date, gt.SUBWAY_DIR / f"{date}.json", gt.SUBWAY_DIR / f"{nxt}.json", gt.WEATHER_DIR / f"{date}.json",
                                 torch.device("cpu"), epochs=1000, patience=0, init_seed=None, diagnostics=d,
                                 assumptions=AssumptionConfig(boarding_headway=headway), capture_ratios=True)
    return pd.DataFrame(rec), d


def main():
    rows, spill_tot, hour_rows = [], np.zeros((20, 21)), []
    for date in CASES:
        B = obs(date)
        fb, db = run(date, False); fh, dh = run(date, True)
        # source-hour -> stop-hour matrix for headway
        M = np.zeros((20, 20))
        for _, r in fh[fh.is_destination == 0].iterrows():
            for sh, amt in json.loads(r.boarding_sources):
                M[sh - 5, r.hour_idx] += amt
        slack_by_src = B.sum(0) - M.sum(1)
        for h in range(20):
            spill_tot[h, :20] += M[h]; spill_tot[h, 20] += slack_by_src[h]
        # mass per stop hour (board entering trains) vs observed hour mass
        mb = fb.groupby("hour_idx").board.sum().reindex(range(20), fill_value=0).to_numpy()
        mh = fh.groupby("hour_idx").board.sum().reindex(range(20), fill_value=0).to_numpy()
        # per-train mean load at peak hours and boarding per non-terminal stop
        nt_b = fb[fb.is_destination == 0].groupby("hour_idx").board.mean(); nt_h = fh[fh.is_destination == 0].groupby("hour_idx").board.mean()
        lb = fb.groupby("hour_idx").load.mean(); lh = fh.groupby("hour_idx").load.mean()
        for h in range(20):
            hour_rows.append(dict(date=date, hour=h + 5, obs_B=B[:, h].sum(), mass_into_trains_base=mb[h], mass_into_trains_headway=mh[h],
                                  board_per_stop_base=nt_b.get(h, np.nan), board_per_stop_headway=nt_h.get(h, np.nan),
                                  mean_load_base=lb.get(h, np.nan), mean_load_headway=lh.get(h, np.nan),
                                  slack_headway_by_source_hour=slack_by_src[h]))
        pb, ph = np.array(db["p_values"]), np.array(dh["p_values"])
        rows.append(dict(date=date, term_base=db["terminal_loss"], term_hw=dh["terminal_loss"], neg_base=db["negative_loss"], neg_hw=dh["negative_loss"],
                         slack_base=B.sum() - db["board_allocated_total"], slack_hw=B.sum() - dh["board_allocated_total"],
                         B_total=B.sum(), p_mean_abs_diff=float(np.abs(pb - ph)[1:-1].mean()),
                         load_p99_base=fb.load.quantile(.99), load_p99_hw=fh.load.quantile(.99),
                         load_mean_base=fb.load.mean(), load_mean_hw=fh.load.mean()))
    pd.DataFrame(rows).to_csv(OUT / "diag_headway_days.csv", index=False)
    pd.DataFrame(hour_rows).to_csv(OUT / "diag_headway_hours.csv", index=False)
    np.save(OUT / "diag_headway_spill_matrix.npy", spill_tot)
    print(pd.DataFrame(rows).round(3).to_string())
    H = pd.DataFrame(hour_rows).groupby("hour").mean(numeric_only=True)
    print(H.round(2).to_string())
    print("spill rows=source hour, share same hour / next hour / slack:")
    for h in range(20):
        t = spill_tot[h].sum()
        print(h + 5, round(spill_tot[h, h] / t, 3), round(spill_tot[h, h + 1] / t, 3) if h < 19 else None, round(spill_tot[h, 20] / t, 4))


if __name__ == "__main__":
    main()
