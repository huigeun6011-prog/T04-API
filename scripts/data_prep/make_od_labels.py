"""Train-level OD (E-16) label generator + dataset assembler (runbook Step 1). Resumable, low priority.

  generate: python scripts/data_prep/make_od_labels.py --dates 2026-10-21,2026-10-24 --out-dir <dir> [--lam 0.01] [--workers 2]
            or --stride 12 --start 2024-11-01 --end 2026-11-01   (every Nth service day)
  assemble: python scripts/data_prep/make_od_labels.py --assemble --out-dir <dir>   -> <dir>/dataset.csv

Per day: labels/<date>.csv (production schema + raw_load/load_correction/terminal_raw_residual, weather attached
with the project rule hour 24 -> next-day 00h), agg/<date>.csv (station x hour x direction mean load), info/<date>.json.
Solver settings are those of gt_train_od (uniform base q, L-BFGS-B); this file changes none of them.
Real peak cases are never read. Existing production files are never touched.
"""
import os
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_v] = "1"
import argparse, ctypes, json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
import gt_train_od as od

COLUMNS = ["date", "train_id", "direction", "dir_code", "day_type", "is_weekend", "station", "station_idx", "time", "hour",
           "hour_idx", "is_origin", "is_destination", "board", "alight", "raw_load", "load_correction", "terminal_raw_residual",
           "load", "precip", "snow", "temp", "plan_version"]


def lower_priority():
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


def weather_lookup(date):
    nxt = (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    look = {}
    for d in (date, nxt):
        p = gt.WEATHER_DIR / f"{d}.json"
        if not p.exists():
            raise FileNotFoundError(f"weather file missing: {p}")
        h = json.loads(p.read_text(encoding="utf-8"))["hourly"]
        for i, stamp in enumerate(h["time"]):
            look[stamp] = (h["precipitation"][i], h["snowfall"][i], h["temperature_2m"][i])
    return look, nxt


def process_day(args):
    date, lam, out = args
    lower_priority()
    out = Path(out)
    lab, info_p, agg_p = out / "labels" / f"{date}.csv", out / "info" / f"{date}.json", out / "agg" / f"{date}.csv"
    if lab.exists() and info_p.exists():
        return dict(date=date, skipped=True)
    t0 = time.perf_counter()
    try:
        look, nxt = weather_lookup(date)
        if not (gt.SUBWAY_DIR / f"{nxt}.json").exists():
            raise FileNotFoundError(f"next-day tap file missing: {nxt}")
        P = od.build_problem(date)
        x, info = od.fit(P, od.base_q(P, "uniform", None, 1.0), lam)
        f = od.to_frame(P, x)
    except Exception as e:     # recorded, the run continues
        return dict(date=date, error=str(e)[:300])
    day_type = gt.get_day_type(date)
    keys = [f"{nxt if h == 24 else date}T{0 if h == 24 else h:02d}:00" for h in f.hour]
    w = np.array([look[k] for k in keys])        # KeyError => stop for this day (no estimated weather)
    f["date"], f["day_type"], f["is_weekend"] = date, day_type, int(day_type == "휴일")
    f["plan_version"] = int(date >= gt.PLAN_CHANGE_DATE)
    f["precip"], f["snow"], f["temp"] = w[:, 0], w[:, 1], w[:, 2]
    f["load_correction"] = f["load"] - f["raw_load"]
    f["terminal_raw_residual"] = np.where(f.is_destination == 1, f.raw_load, np.nan)
    f = f[COLUMNS]
    for d in ("labels", "info", "agg"):
        (out / d).mkdir(parents=True, exist_ok=True)
    agg = f.groupby(["station_idx", "hour", "dir_code"]).load.agg(["mean", "max", "count"]).reset_index()
    agg.insert(0, "date", date)
    agg.to_csv(agg_p, index=False)
    ms = od.marginal_stats(P, od.to_frame(P, x))
    term = float(f.loc[f.is_destination == 1, "raw_load"].abs().max())
    f.to_csv(lab.with_suffix(".tmp"), index=False, encoding="utf-8")
    lab.with_suffix(".tmp").replace(lab)
    rec = dict(date=date, lam=lam, seconds=time.perf_counter() - t0, rows=len(f), converged=info["converged"], nit=info["nit"],
               objective=info["objective"], proj_grad_inf=info["proj_grad_inf"], message=info["message"],
               terminal_abs_max=term, raw_load_min=float(f.raw_load.min()),
               B_rel_l1_eligible=ms["B_rel_l1_eligible"], A_rel_l1_eligible=ms["A_rel_l1_eligible"],
               board_slack_nocell=ms["B_slack_nocell"], alight_slack_nocell=ms["A_slack_nocell"])
    info_p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def assemble(out):
    out = Path(out); files = sorted((out / "labels").glob("*.csv"))
    if not files:
        raise SystemExit("no label files")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    assert list(df.columns) == COLUMNS, "column mismatch"
    df.to_csv(out / "dataset.csv", index=False, encoding="utf-8")
    infos = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "info").glob("*.json"))]
    rep = dict(n_days=len(files), rows=len(df), unseen_nan_weather=int(df[["precip", "snow", "temp"]].isna().sum().sum()),
               not_converged=sum(not i["converged"] for i in infos), terminal_abs_max=max(i["terminal_abs_max"] for i in infos),
               raw_load_min=float(df.raw_load.min()), columns_ok=True, dates=[f.stem for f in files])
    (out / "assemble_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "dates"}, ensure_ascii=False))


def pick_dates(a):
    if a.dates:
        return a.dates.split(",")
    days = pd.date_range(a.start, a.end).strftime("%Y-%m-%d").tolist()
    return days[::a.stride]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates"); ap.add_argument("--stride", type=int, default=0)
    ap.add_argument("--start", default="2024-11-01"); ap.add_argument("--end", default="2026-11-01")
    ap.add_argument("--out-dir", type=Path, required=True); ap.add_argument("--lam", type=float, default=0.01)
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--assemble", action="store_true")
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.assemble:
        return assemble(a.out_dir)
    dates = pick_dates(a)
    workers = max(1, min(a.workers, 3))
    (a.out_dir / "config.json").write_text(json.dumps(dict(dates=dates, lam=a.lam, workers=workers, base="uniform", solver="gt_train_od.fit L-BFGS-B"),
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
    done, errs = 0, []
    with ProcessPoolExecutor(workers) as ex:
        for r in ex.map(process_day, [(d, a.lam, str(a.out_dir)) for d in dates]):
            done += 1
            if "error" in r:
                errs.append(r)
            (a.out_dir / "progress.json").write_text(json.dumps(dict(done=done, total=len(dates), errors=errs, last=r.get("date"),
                                                                     time=time.strftime("%Y-%m-%d %H:%M:%S"))), encoding="utf-8")
            print(json.dumps({k: r.get(k) for k in ("date", "skipped", "seconds", "converged", "nit", "error")}, ensure_ascii=False), flush=True)
    print(f"finished {done}/{len(dates)}, errors {len(errs)}")


if __name__ == "__main__":
    main()
