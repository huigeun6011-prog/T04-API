"""Feasibility upper-bound diagnostic for the 19 matched real peak cases.

DIAGNOSIS ONLY. Nothing here is used for tuning/training/calibration.
Hourly tap counts are per station (both directions combined, not split), so a
single train's bound using them is intentionally generous.
Run: .venv/Scripts/python.exe scripts/data_prep/diagnose_feasibility_bound.py
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt  # noqa: E402  (reuse project schedule rules)

OUT = ROOT / "outputs/diagnostics/feasibility_bound"
_cache = {}


def hourly(date_str):
    """station name -> (boardings{h:int}, alightings{h:int}) for a calendar date."""
    if date_str not in _cache:
        p = gt.SUBWAY_DIR / f"{date_str}.json"
        _cache[date_str] = json.loads(p.read_text(encoding="utf-8"))["stations"] if p.exists() else None
    return _cache[date_str]


def tap(service_date, station, hour, kind):
    """Taps at station in service-day hour (24 -> next calendar date 00h). None if missing."""
    d, h = service_date, hour
    if h >= 24:
        d = (datetime.strptime(service_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        h -= 24
    st = hourly(d)
    if st is None:
        return None
    sid = str(101 + gt.STATION_TO_IDX[station])
    return st[sid][kind].get(str(h), 0)


def bounds(date, train, peak_station, shift):
    """Sum taps over stations before the peak station, per-station stop hour (+shift)."""
    stops = train["stops"]
    k = [s["station"] for s in stops].index(peak_station)
    b = a = 0
    for s in stops[:k]:
        h = int(s["time"].split(":")[0]) + shift
        bb, aa = tap(date, s["station"], h, "boardings"), tap(date, s["station"], h, "alightings")
        if bb is None or aa is None or not 5 <= h <= 24:
            return None
        b += bb
        a += aa
    h = int(stops[k]["time"].split(":")[0]) + shift
    own = tap(date, peak_station, h, "boardings")
    return b, a, own


def n_trains(date, direction, station, hour, day_type):
    n = 0
    for t in gt.get_subway_trains(date, day_type):
        if t["direction"] != direction:
            continue
        for s in t["stops"]:
            if s["station"] == station and int(s["time"].split(":")[0]) == hour:
                n += 1
    return n


def main():
    cases = pd.read_csv(next((ROOT / "data/raw/subway_time").glob("*20261031.csv")), encoding="cp949")
    comp = pd.read_csv(ROOT / "outputs/peak_case_comparison.csv", encoding="utf-8-sig")
    comp = comp[comp.status == "matched"]
    rows = []
    for _, c in comp.iterrows():
        date, pk, d = c.service_date, c.peak_station, c.direction
        day_type = gt.get_day_type(date)
        cand = [t for t in gt.get_subway_trains(date, day_type) if t["train_id"] == c.synthetic_train_id]
        if len(cand) != 1:
            rows.append(dict(service_date=date, train=c.official_train_number, note="train not found"))
            continue
        tr = cand[0]
        stops = tr["stops"]
        k = [s["station"] for s in stops].index(pk)
        ph = int(stops[k]["time"].split(":")[0])
        hrs = sorted({int(s["time"].split(":")[0]) for s in stops[:k + 1]})
        r = dict(service_date=date, official_train=int(c.official_train_number), direction=d, origin=tr["origin"],
                 peak_station=pk, n_upstream=k, peak_stop_time=stops[k]["time"], hours_spanned=str(hrs),
                 straddles_hour=len(hrs) > 1, actual=float(c.actual_peak_load),
                 label=float(c.estimated_label_load), plan="20260330" if (date >= gt.PLAN_CHANGE_DATE and day_type == "평일") else "20250930")
        for tag, shift in (("", 0), ("_prev", -1), ("_next", 1)):
            res = bounds(date, tr, pk, shift)
            if res is None:
                r.update({f"loose{tag}": np.nan, f"loose_incl_own{tag}": np.nan, f"tight{tag}": np.nan,
                          f"tight_incl_own{tag}": np.nan})
                continue
            b, a, own = res
            r.update({f"loose{tag}": b, f"loose_incl_own{tag}": b + own, f"tight{tag}": b - a,
                      f"tight_incl_own{tag}": b - a + own})
            if tag == "":
                r.update(sum_board_upstream=b, sum_alight_upstream=a, own_board=own)
        nd = n_trains(date, d, pk, ph, day_type)
        nu = n_trains(date, "상행", pk, ph, day_type) + n_trains(date, "하행", pk, ph, day_type)
        r.update(n_trains_dir_peak_hour=nd, n_trains_both_dirs_peak_hour=nu)
        r["mean_share_dir"] = r["tight"] / nd if nd else np.nan
        r["mean_share_both_dirs"] = r["tight"] / nu if nu else np.nan
        # direction-agnostic caveat: station taps mix both directions, so the net (tight) variant can go
        # negative/meaningless. Boarding-only half-split is a more usable even-share reference.
        r["mean_share_board_half"] = 0.5 * r["loose"] / nd if nd else np.nan
        r["conc_factor_board_half"] = r["actual"] / r["mean_share_board_half"]
        r["actual_over_loose"] = r["actual"] / r["loose"]
        r["actual_over_loose_incl_own"] = r["actual"] / r["loose_incl_own"]
        r["actual_over_tight"] = r["actual"] / r["tight"]
        r["conc_factor_dir"] = r["actual"] / r["mean_share_dir"]
        r["conc_factor_both_dirs"] = r["actual"] / r["mean_share_both_dirs"]
        r["label_over_actual"] = r["label"] / r["actual"]
        r["label_conc_factor_dir"] = r["label"] / r["mean_share_dir"]
        r["gt_label_vs_mean_share_dir"] = r["label"] / r["mean_share_dir"]
        r["gt_over_loose"] = r["label"] / r["loose"]
        rows.append(r)
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "feasibility_bound.csv", index=False, encoding="utf-8-sig")

    ok = df.dropna(subset=["loose"])
    s = {"n_cases": int(len(df)), "n_with_data": int(len(ok)),
         "actual_gt_loose": int((ok.actual > ok.loose).sum()),
         "actual_gt_loose_incl_own": int((ok.actual > ok.loose_incl_own).sum()),
         "actual_gt_tight": int((ok.actual > ok.tight).sum()),
         "actual_gt_tight_incl_own": int((ok.actual > ok.tight_incl_own).sum()),
         "n_straddle_hour": int(ok.straddles_hour.sum()),
         "actual_gt_tight_any_adjacent_hour_max": int((ok.actual > ok[["tight", "tight_prev", "tight_next"]].max(axis=1)).sum()),
         "conc_factor_dir": ok.conc_factor_dir.describe().round(3).to_dict(),
         "conc_factor_both_dirs": ok.conc_factor_both_dirs.describe().round(3).to_dict(),
         "conc_factor_board_half": ok.conc_factor_board_half.describe().round(3).to_dict(),
         "conc_board_half_le_2": int((ok.conc_factor_board_half <= 2).sum()),
         "conc_board_half_gt_3": int((ok.conc_factor_board_half > 3).sum()),
         "conc_dir_gt_3": int((ok.conc_factor_dir > 3).sum()), "conc_dir_gt_2": int((ok.conc_factor_dir > 2).sum()),
         "conc_dir_le_2": int((ok.conc_factor_dir <= 2).sum()),
         "conc_both_gt_3": int((ok.conc_factor_both_dirs > 3).sum()),
         "actual_over_loose": ok.actual_over_loose.describe().round(3).to_dict(),
         "actual_over_tight": ok.actual_over_tight.describe().round(3).to_dict(),
         "label_over_actual_mean": float(ok.label_over_actual.mean()),
         "label_over_mean_share_dir_mean": float(ok.label_conc_factor_dir.mean()),
         "assumptions": ["tap counts are per station, both directions combined (no direction split)",
                         "each upstream station uses the hour of the train's own stop there; adjacent-hour variants shift all by +-1h",
                         "mean-share = tight net / trains of that direction stopping at the peak station in the peak stop hour",
                         "mean_share_board_half = 0.5*loose boardings / trains(dir) (even direction split, no alighting)",
                         "diagnostic only; no calibration"]}
    (OUT / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(df[["service_date", "official_train", "direction", "peak_station", "actual", "loose", "loose_incl_own", "tight",
              "mean_share_dir", "conc_factor_dir", "n_trains_dir_peak_hour", "mean_share_board_half", "conc_factor_board_half", "label", "straddles_hour"]].round(2).to_string())
    print(json.dumps(s, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
