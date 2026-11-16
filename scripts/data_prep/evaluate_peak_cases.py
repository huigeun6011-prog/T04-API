"""Compare the 20 supplied peak cases with the estimated labels and model.

These selected extreme cases are external spot checks, not training labels or
an unbiased accuracy estimate. Official train numbers are not the synthetic
schedule IDs, so matching uses service date, direction, origin and departure.
"""
import json
import argparse
from pathlib import Path
import sys
import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_ground_truth as gt


def main():
    parser = argparse.ArgumentParser(description="실제 피크 사례 사후 검증 (학습/튜닝 입력 아님)")
    parser.add_argument("--model", type=Path, default=ROOT / "outputs/load_predictor.joblib")
    parser.add_argument("--dataset", type=Path, default=ROOT / "outputs/ground_truth_train_loads.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = next((ROOT / "data/raw/subway_time").glob("*20261031.csv"))
    cases = pd.read_csv(source, encoding="cp949")
    model = joblib.load(args.model)
    features = list(model.feature_names_in_)
    records = []
    for _, row in cases.iterrows():
        date = row["영업일"]
        day_type = gt.get_day_type(date)
        candidates = [t for t in gt.get_subway_trains(date, day_type)
                      if t["direction"] == row["상_하행"]
                      and t["origin"] == row["출발역"]
                      and t["origin_depart"] == row["출발시간"][:5]]
        record = {"service_date": date, "official_train_number": int(row["열차번호"]),
                  "direction": row["상_하행"], "peak_station": row["최고혼잡역"],
                  "actual_peak_load": float(row["재차인원"])}
        matches = [(t, st) for t in candidates for st in t["stops"] if st["station"] == row["최고혼잡역"]]
        if len(matches) != 1:
            record.update(status="unmatched_or_ambiguous_schedule", matched_count=len(matches))
            records.append(record)
            continue
        train, stop = matches[0]
        hour = gt.normalize_hour(int(stop["time"].split(":")[0]))
        actual_date = (pd.Timestamp(date) + pd.Timedelta(days=int(hour == 24))).strftime("%Y-%m-%d")
        weather = json.loads((gt.WEATHER_DIR / f"{actual_date}.json").read_text(encoding="utf-8"))["hourly"]
        stamp = f"{actual_date}T{0 if hour == 24 else hour:02d}:00"
        i = weather["time"].index(stamp)
        x = pd.DataFrame([{"station_idx": gt.STATION_TO_IDX[stop["station"]], "hour": hour,
                           "dir_code": int(row["상_하행"] == "하행"), "is_weekend": int(day_type == "휴일"),
                           "temp": weather["temperature_2m"][i], "precip": weather["precipitation"][i],
                           "snow": weather["snowfall"][i], "plan_version": int(date >= gt.PLAN_CHANGE_DATE)}])
        prediction = max(0, float(model.predict(x[features])[0]))
        record.update(status="matched", synthetic_train_id=train["train_id"], peak_stop_time=stop["time"],
                      predicted_load=round(prediction, 2), error=round(prediction-record["actual_peak_load"], 2))
        records.append(record)
    report = pd.DataFrame(records)
    lookup = {}
    for chunk in pd.read_csv(args.dataset, usecols=["date", "train_id", "station", "time", "load"], chunksize=100000):
        for _, item in chunk[chunk["date"].isin(set(report.service_date))].iterrows():
            lookup[(item["date"], item["train_id"], item["station"], item["time"])] = float(item["load"])
    report["estimated_label_load"] = [lookup.get((r["service_date"], r.get("synthetic_train_id"), r["peak_station"], r.get("peak_stop_time"))) for r in records]
    report["label_error"] = report["estimated_label_load"] - report["actual_peak_load"]
    report.to_csv(args.output_dir / "peak_case_comparison.csv", encoding="utf-8-sig", index=False)
    matched = report[report.status == "matched"]
    summary = {"n_cases": len(report), "n_matched": len(matched),
               "matched_mae": float(matched.error.abs().mean()) if len(matched) else None,
               "matched_bias": float(matched.error.mean()) if len(matched) else None,
               "estimated_label_mae": float(matched.label_error.abs().mean()) if len(matched) else None,
               "caveat": "Selected peak cases, model predicts hour-conditioned post-stop estimated loads. In-sample dates after full refit; not independent holdout accuracy. Actual peak count may be measured before versus after stop; no such measurement metadata is supplied."}
    (args.output_dir / "peak_case_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
