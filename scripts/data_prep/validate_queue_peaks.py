"""ONE post-hoc, report-only comparison of the frozen queue arms with the 19 matched peak cases.
Run only after experiment_queue_model.py is finished. Nothing here feeds back into any model.
"""
import json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt
import experiment_queue_model as ex

OUT = gt.ROOT / "outputs/diagnostics/queue_model"
ARMS = ["baseline", "boarding_headway"] + list(ex.CAPS)


def job(args):
    arm, date = args
    _, frame = ex.run_arm(arm, date, None, ex.EPOCHS, keep_frame=True)
    return arm, date, frame


def main():
    comp = pd.read_csv(gt.ROOT / "outputs/peak_case_comparison.csv", encoding="utf-8-sig")
    comp = comp[comp.status == "matched"].reset_index(drop=True)
    feas = pd.read_csv(gt.ROOT / "outputs/diagnostics/feasibility_bound/feasibility_bound.csv", encoding="utf-8-sig")
    comp = comp.merge(feas[["service_date", "official_train", "mean_share_board_half", "conc_factor_board_half"]],
                      left_on=["service_date", "official_train_number"], right_on=["service_date", "official_train"])
    dates = sorted(comp.service_date.unique())
    frames = {}
    with ProcessPoolExecutor(12) as pool:
        for arm, date, fr in pool.map(job, [(a, d) for a in ARMS for d in dates]):
            frames[(arm, date)] = fr
    rows = []
    for _, c in comp.iterrows():
        r = dict(service_date=c.service_date, train=c.official_train_number, direction=c.direction, peak_station=c.peak_station,
                 actual=c.actual_peak_load, even_share_ref=c.mean_share_board_half, needed_conc=c.conc_factor_board_half)
        for arm in ARMS:
            f = frames[(arm, c.service_date)]
            row = f[(f.train_id == c.synthetic_train_id) & (f.station == c.peak_station)]
            assert len(row) == 1
            est = float(row.load.iloc[0])
            r[arm + "_est"] = est
            r[arm + "_est_over_actual"] = est / c.actual_peak_load
            r[arm + "_conc"] = est / c.mean_share_board_half
        rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "peak_posthoc.csv", index=False, encoding="utf-8-sig")
    s = {arm: dict(mean_est_over_actual=float(df[arm + "_est_over_actual"].mean()),
                   min=float(df[arm + "_est_over_actual"].min()), max=float(df[arm + "_est_over_actual"].max()),
                   mae=float((df[arm + "_est"] - df.actual).abs().mean()), mean_conc=float(df[arm + "_conc"].mean()))
         for arm in ARMS}
    s["needed_conc_mean"] = float(df.needed_conc.mean())
    (OUT / "peak_posthoc_summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
