"""ONE post-hoc, report-only comparison of the frozen OD-prior arms with the 19 matched peak cases.
Also recomputes the even-share reference with data-derived direction shares instead of 50:50.
Nothing here feeds back into any model."""
import json, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
import experiment_od_prior as ex

OUT = gt.ROOT / "outputs/diagnostics/od_prior"


def job(a):
    arm, date = a
    return arm, date, ex.od.solve_day(date, ex.ARM_CFG[arm], ex.EPOCHS, None, {})


def main():
    comp = pd.read_csv(gt.ROOT / "outputs/peak_case_comparison.csv", encoding="utf-8-sig")
    comp = comp[comp.status == "matched"].reset_index(drop=True)
    feas = pd.read_csv(gt.ROOT / "outputs/diagnostics/feasibility_bound/feasibility_bound.csv", encoding="utf-8-sig")
    comp = comp.merge(feas[["service_date", "official_train", "n_trains_dir_peak_hour", "mean_share_board_half", "conc_factor_board_half"]],
                      left_on=["service_date", "official_train_number"], right_on=["service_date", "official_train"])
    dates = sorted(comp.service_date.unique())
    res = {}
    with ProcessPoolExecutor(12) as pool:
        for arm, d, out in pool.map(job, [(a, d) for a in ex.ARMS for d in dates]):
            res[(arm, d)] = out
    rows = []
    for _, c in comp.iterrows():
        day_type = gt.get_day_type(c.service_date)
        train = [t for t in gt.get_subway_trains(c.service_date, day_type) if t["train_id"] == c.synthetic_train_id][0]
        names = [s["station"] for s in train["stops"]]
        k = names.index(c.peak_station)
        r = dict(service_date=c.service_date, train=c.official_train_number, direction=c.direction, peak_station=c.peak_station,
                 actual=c.actual_peak_load, ref_5050=c.mean_share_board_half, needed_conc_5050=c.conc_factor_board_half)
        for arm in ex.ARMS:
            frame, aux = res[(arm, c.service_date)]
            row = frame[(frame.train_id == c.synthetic_train_id) & (frame.station == c.peak_station)]
            est = float(row.load.iloc[0])
            r[arm + "_est"] = est
            r[arm + "_est_over_actual"] = est / c.actual_peak_load
            if arm != "baseline":
                for tag, p in (("hat", aux["p_hat"]), ("fit", aux["p_fit"])):
                    tot = 0.0
                    for s in train["stops"][:k]:
                        h = gt.HOUR_TO_IDX[gt.normalize_hour(int(s["time"].split(":")[0]))]
                        i = gt.STATION_TO_IDX[s["station"]]
                        share = p[i, h] if c.direction == "상행" else 1 - p[i, h]
                        tot += aux["B"][i, h] * share
                    r[f"{arm}_ref_{tag}"] = tot / c.n_trains_dir_peak_hour
                    r[f"{arm}_needed_conc_{tag}"] = c.actual_peak_load / r[f"{arm}_ref_{tag}"]
        rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "peak_posthoc.csv", index=False, encoding="utf-8-sig")
    s = {}
    for arm in ex.ARMS:
        e = df[arm + "_est"]
        s[arm] = dict(mean_est_over_actual=float(df[arm + "_est_over_actual"].mean()), min=float(df[arm + "_est_over_actual"].min()),
                      max=float(df[arm + "_est_over_actual"].max()), mae=float((e - df.actual).abs().mean()))
        if arm != "baseline":
            s[arm].update(needed_conc_hat_mean=float(df[arm + "_needed_conc_hat"].mean()), needed_conc_hat_median=float(df[arm + "_needed_conc_hat"].median()),
                          needed_conc_fit_mean=float(df[arm + "_needed_conc_fit"].mean()))
    s["needed_conc_5050_mean"] = float(df.needed_conc_5050.mean())
    (OUT / "peak_posthoc_summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    print(pd.DataFrame(s).T.round(3).to_string())


if __name__ == "__main__":
    main()
